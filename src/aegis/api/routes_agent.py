"""Agent run endpoints — trigger a run and inspect its trace.

`GET /runs/{run_id}` reuses `TraceStore.replay()` to return the full
step-by-step trace: the same data structure that would be used to
deterministically replay the run is what the console (Sprint 4) renders as
the "step through this run" view.

The caller never supplies `tenant_id` directly — it comes from the
authenticated `Principal` (see aegis.tenancy.rbac), and a developer/viewer
can only ever see their own tenant's runs, enforced by `TraceStore` filtering
at the query level, not by hiding rows in the response.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.agent.runtime import AgentConfig, AgentRuntime
from aegis.agent.tools.calculator import CalculatorTool
from aegis.agent.tools.http_allowlist import HttpAllowlistTool
from aegis.agent.tools.knowledge_base import KnowledgeBaseSearchTool
from aegis.agent.tools.registry import ToolRegistry
from aegis.agent.tools.sql_readonly import SqlReadOnlyTool
from aegis.agent.trace import TraceStore
from aegis.config import settings
from aegis.cost.budgets import BudgetEnforcer, BudgetStatus
from aegis.cost.tracker import CostTracker
from aegis.db.session import get_session
from aegis.governance.audit import AuditStore
from aegis.providers.router import RoutingContext
from aegis.tenancy.models import Role
from aegis.tenancy.rbac import Principal, require_role

router = APIRouter(prefix="/v1/agents", tags=["agents"])


class AgentRunIn(BaseModel):
    agent_name: str = "default"
    system_prompt: str = "You are a helpful assistant with access to tools."
    user_message: str
    data_classification: str = "internal"
    cost_tier: str = "standard"
    max_steps: int = 8
    token_budget: int = 20_000


class AgentRunOut(BaseModel):
    run_id: uuid.UUID
    status: str
    final_output: str | None
    total_input_tokens: int
    total_output_tokens: int
    step_count: int


class AgentStepOut(BaseModel):
    step_type: str
    tool_name: str | None
    provider_name: str | None
    model: str | None
    input: dict
    output: dict | None
    error: str | None
    input_tokens: int
    output_tokens: int
    retry_count: int
    duration_ms: int | None


class AgentRunDetailOut(BaseModel):
    run_id: uuid.UUID
    status: str
    final_output: str | None
    total_input_tokens: int
    total_output_tokens: int
    steps: list[AgentStepOut]


class AgentRunSummaryOut(BaseModel):
    run_id: uuid.UUID
    agent_name: str
    status: str
    step_count: int
    total_input_tokens: int
    total_output_tokens: int
    created_at: str
    completed_at: str | None


def _build_tools(session: AsyncSession) -> ToolRegistry:
    return ToolRegistry(
        [
            CalculatorTool(),
            KnowledgeBaseSearchTool(),
            SqlReadOnlyTool(session),
            HttpAllowlistTool(allowed_domains=settings.http_tool_allowed_domains_list),
        ]
    )


@router.post("/run", response_model=AgentRunOut)
async def run_agent(
    body: AgentRunIn,
    request: Request,
    principal: Principal = Depends(require_role(Role.DEVELOPER)),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    tenant_id = principal.tenant_id
    tenant = request.app.state.tenants.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"unknown tenant: {tenant_id}")

    cost_tracker = CostTracker(session, request.app.state.pricing)
    budget = await BudgetEnforcer(cost_tracker).check(tenant_id, tenant.monthly_budget_usd)
    if budget.status == BudgetStatus.HARD_STOP:
        await AuditStore(session).record(
            tenant_id=tenant_id, action="budget_hard_stop", actor=principal.key_id
        )
        await session.commit()
        raise HTTPException(
            status_code=429,
            detail=(
                f"monthly budget exhausted: ${budget.month_to_date_usd:.4f} "
                f"of ${budget.monthly_budget_usd:.2f}"
            ),
        )

    provider_router = request.app.state.provider_router
    tools = _build_tools(session)
    trace_store = TraceStore(session)
    config = AgentConfig(max_steps=body.max_steps, token_budget=body.token_budget)
    audit_store = AuditStore(session)
    runtime = AgentRuntime(
        provider_router,
        tools,
        trace_store,
        config,
        guardrails=request.app.state.guardrails,
        cost_tracker=cost_tracker,
        audit_store=audit_store,
    )

    context = RoutingContext(
        tenant_id=tenant_id,
        data_classification=body.data_classification,
        cost_tier=body.cost_tier,
    )
    result = await runtime.run(
        tenant_id,
        body.agent_name,
        body.system_prompt,
        body.user_message,
        context,
        guardrail_policy_name=tenant.guardrail_policy,
    )
    await audit_store.record(
        tenant_id=tenant_id,
        run_id=result.run_id,
        action="agent_run",
        actor=principal.key_id,
        input_tokens=result.total_input_tokens,
        output_tokens=result.total_output_tokens,
    )
    await session.commit()

    return AgentRunOut(
        run_id=result.run_id,
        status=result.status,
        final_output=result.final_output,
        total_input_tokens=result.total_input_tokens,
        total_output_tokens=result.total_output_tokens,
        step_count=result.step_count,
    )


@router.get("/runs", response_model=list[AgentRunSummaryOut])
async def list_agent_runs(
    limit: int = 50,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_session),
) -> list[AgentRunSummaryOut]:
    tenant_filter = None if principal.role == Role.ADMIN else principal.tenant_id
    runs = await TraceStore(session).list_runs(tenant_id=tenant_filter, limit=limit)
    return [
        AgentRunSummaryOut(
            run_id=run.id,
            agent_name=run.agent_name,
            status=run.status,
            step_count=run.step_count,
            total_input_tokens=run.total_input_tokens,
            total_output_tokens=run.total_output_tokens,
            created_at=run.created_at.isoformat(),
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
        )
        for run in runs
    ]


@router.get("/runs/{run_id}", response_model=AgentRunDetailOut)
async def get_agent_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_session),
) -> AgentRunDetailOut:
    trace_store = TraceStore(session)
    tenant_filter = None if principal.role == Role.ADMIN else principal.tenant_id
    try:
        replayed = await trace_store.replay(run_id, tenant_id=tenant_filter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return AgentRunDetailOut(
        run_id=replayed.run_id,
        status=replayed.status,
        final_output=replayed.final_output,
        total_input_tokens=replayed.total_input_tokens,
        total_output_tokens=replayed.total_output_tokens,
        steps=[
            AgentStepOut(
                step_type=s.step_type,
                tool_name=s.tool_name,
                provider_name=s.provider_name,
                model=s.model,
                input=s.input,
                output=s.output,
                error=s.error,
                input_tokens=s.input_tokens,
                output_tokens=s.output_tokens,
                retry_count=s.retry_count,
                duration_ms=s.duration_ms,
            )
            for s in replayed.steps
        ],
    )
