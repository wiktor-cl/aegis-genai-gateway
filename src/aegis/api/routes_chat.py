"""Minimal chat completion endpoint proving the provider router end-to-end.

This is intentionally thin for Sprint 1: no guardrails, cost accounting, or
multi-tenancy enforcement yet — those land in Sprint 3 (governance, cost,
RBAC) and wrap this same router call, they do not replace it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from aegis.providers.base import ChatMessage, ChatRequest, ProviderError
from aegis.providers.router import NoHealthyProviderError, RoutingContext

router = APIRouter(prefix="/v1", tags=["chat"])


class ChatCompletionIn(BaseModel):
    tenant_id: str
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
async def create_chat_completion(body: ChatCompletionIn, request: Request) -> ChatCompletionOut:
    request_id = str(uuid.uuid4())
    chat_request = ChatRequest(
        messages=body.messages,
        model=body.model,
        temperature=body.temperature,
        max_output_tokens=body.max_output_tokens,
        tenant_id=body.tenant_id,
        request_id=request_id,
    )
    context = RoutingContext(
        tenant_id=body.tenant_id,
        data_classification=body.data_classification,
        cost_tier=body.cost_tier,
    )

    provider_router = request.app.state.provider_router
    try:
        response = await provider_router.route(chat_request, context)
    except NoHealthyProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatCompletionOut(
        request_id=request_id,
        provider=response.provider_name,
        model=response.model,
        content=response.message.content,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        finish_reason=response.finish_reason,
    )
