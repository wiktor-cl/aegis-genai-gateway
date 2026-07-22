"""Single-shot chat completion endpoint — the simplest possible entry point
into the provider router (ADR-0002), guarded the same way agent runs are
(ADR-0001's "guardrails wired once, at the interface boundary" principle
applied at every entry point, not just the agent runtime): the caller's
tenant comes from the authenticated `Principal`, guardrails screen the last
user message and the response, and every call is cost-tracked.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.cost.tracker import CostTracker
from aegis.db.session import get_session
from aegis.governance.audit import AuditStore
from aegis.providers.base import ChatMessage, ChatRequest, ProviderError, Role
from aegis.providers.router import NoHealthyProviderError, RoutingContext
from aegis.tenancy.models import Role as TenantRole
from aegis.tenancy.rbac import Principal, require_role

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatCompletionIn(BaseModel):
    messages: list[ChatMessage]
    data_classification: str = "internal"
    cost_tier: str = "standard"
    model: str = ""
    temperature: float = 0.2
    max_output_tokens: int = 1024


class ChatCompletionOut(BaseModel):
    request_id: str
    provider: str
    model: str
    content: str
    input_tokens: int
    output_tokens: int
    finish_reason: str


@router.post("/chat/completions", response_model=ChatCompletionOut)
async def create_chat_completion(
    body: ChatCompletionIn,
    request: Request,
    principal: Principal = Depends(require_role(TenantRole.DEVELOPER)),
    session: AsyncSession = Depends(get_session),
) -> ChatCompletionOut:
    tenant_id = principal.tenant_id
    tenant = request.app.state.tenants.get(tenant_id)
    guardrail_policy = tenant.guardrail_policy if tenant else None

    guardrails = request.app.state.guardrails
    audit = AuditStore(session)

    last_user_message = next(
        (m.content for m in reversed(body.messages) if m.role == Role.USER), ""
    )
    pre = guardrails.screen_request(last_user_message, guardrail_policy)
    for hit in pre.hits:
        await audit.record(
            tenant_id=tenant_id,
            action="guardrail_request",
            actor=principal.key_id,
            policy_rule=hit.rule,
            policy_action=hit.action,
            detail={"matches": hit.detail},
        )
    if not pre.allowed:
        await session.commit()
        raise HTTPException(status_code=400, detail=pre.block_reason)

    request_id = str(uuid.uuid4())
    chat_request = ChatRequest(
        messages=body.messages,
        model=body.model,
        temperature=body.temperature,
        max_output_tokens=body.max_output_tokens,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    context = RoutingContext(
        tenant_id=tenant_id,
        data_classification=body.data_classification,
        cost_tier=body.cost_tier,
    )

    provider_router = request.app.state.provider_router
    try:
        response = await provider_router.route(chat_request, context)
    except NoHealthyProviderError as exc:
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        await session.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    post = guardrails.screen_response(response.message.content, guardrail_policy)
    for hit in post.hits:
        await audit.record(
            tenant_id=tenant_id,
            action="guardrail_response",
            actor=principal.key_id,
            policy_rule=hit.rule,
            policy_action=hit.action,
            detail={"matches": hit.detail},
        )
    if not post.allowed:
        await session.commit()
        raise HTTPException(status_code=502, detail=post.block_reason)

    await CostTracker(session, request.app.state.pricing).record(
        tenant_id,
        response.provider_name,
        response.model,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    await session.commit()

    return ChatCompletionOut(
        request_id=request_id,
        provider=response.provider_name,
        model=response.model,
        content=post.text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        finish_reason=response.finish_reason,
    )
