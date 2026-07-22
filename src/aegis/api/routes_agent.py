"""Agent run endpoints — trigger a run and inspect its trace.

`GET /runs/{run_id}` reuses `TraceStore.replay()` to return the full
step-by-step trace: the same data structure that would be used to
deterministically replay the run is what the console (Sprint 4) renders as
the "step through this run" view.
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
from aegis.db.session import get_session
from aegis.providers.router import RoutingContext

router = APIRouter(prefix="/v1/agents", tags=["agents"])


class AgentRunIn(BaseModel):
    tenant_id: str
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
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    provider_router = request.app.state.provider_router
    tools = _build_tools(session)
    trace_store = TraceStore(session)
    config = AgentConfig(max_steps=body.max_steps, token_budget=body.token_budget)
    runtime = AgentRuntime(provider_router, tools, trace_store, config)

    context = RoutingContext(
        tenant_id=body.tenant_id,
        data_classification=body.data_classification,
        cost_tier=body.cost_tier,
    )
    result = await runtime.run(
        body.tenant_id, body.agent_name, body.system_prompt, body.user_message, context
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


@router.get("/runs/{run_id}", response_model=AgentRunDetailOut)
async def get_agent_run(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AgentRunDetailOut:
    trace_store = TraceStore(session)
    try:
        replayed = await trace_store.replay(run_id)
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
