"""Persists agent runs/steps and supports deterministic replay from storage.

`TraceStore` is the only thing in the agent runtime that talks to the
database — `AgentRuntime` (runtime.py) calls it to open a run, record each
step, and close the run. `replay()` reconstructs a run's outcome purely from
those stored rows, without calling any provider or tool again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.db.models import AgentRun, AgentStep


@dataclass
class StepRecord:
    step_type: str
    input: dict
    output: dict | None = None
    error: str | None = None
    provider_name: str | None = None
    model: str | None = None
    tool_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    retry_count: int = 0
    duration_ms: int | None = None


@dataclass
class ReplayedRun:
    run_id: uuid.UUID
    status: str
    final_output: str | None
    total_input_tokens: int
    total_output_tokens: int
    steps: list[StepRecord] = field(default_factory=list)


class TraceStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start_run(
        self,
        tenant_id: str,
        agent_name: str,
        max_steps: int,
        token_budget: int,
        data_classification: str = "internal",
        cost_tier: str = "standard",
    ) -> uuid.UUID:
        run = AgentRun(
            tenant_id=tenant_id,
            agent_name=agent_name,
            status="running",
            max_steps=max_steps,
            token_budget=token_budget,
            data_classification=data_classification,
            cost_tier=cost_tier,
        )
        self._session.add(run)
        await self._session.flush()
        return run.id

    async def record_step(self, run_id: uuid.UUID, step_index: int, record: StepRecord) -> None:
        step = AgentStep(
            run_id=run_id,
            step_index=step_index,
            step_type=record.step_type,
            provider_name=record.provider_name,
            model=record.model,
            tool_name=record.tool_name,
            input=record.input,
            output=record.output,
            error=record.error,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            retry_count=record.retry_count,
            finished_at=datetime.now(UTC),
            duration_ms=record.duration_ms,
        )
        self._session.add(step)

        run = await self._session.get(AgentRun, run_id)
        assert run is not None
        run.step_count += 1
        run.total_input_tokens += record.input_tokens
        run.total_output_tokens += record.output_tokens
        await self._session.flush()

    async def finish_run(
        self,
        run_id: uuid.UUID,
        status: str,
        final_output: str | None = None,
        error: str | None = None,
    ) -> None:
        run = await self._session.get(AgentRun, run_id)
        assert run is not None
        run.status = status
        run.final_output = final_output
        run.error = error
        run.completed_at = datetime.now(UTC)
        await self._session.flush()

    async def list_runs(self, tenant_id: str | None = None, limit: int = 50) -> list[AgentRun]:
        """Most recent runs first — the console's "recent runs" view. Same
        tenant-scoping-at-the-query-level rule as `get_run`/`replay` (ADR-0005):
        `tenant_id=None` (admin only, enforced by the API route) returns runs
        across every tenant."""
        query = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        if tenant_id is not None:
            query = query.where(AgentRun.tenant_id == tenant_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_run(self, run_id: uuid.UUID, tenant_id: str | None = None) -> AgentRun | None:
        """`tenant_id`, when given, is enforced as a WHERE clause on the
        query itself — not a post-fetch check — so a developer/viewer role
        can never even observe that a run belonging to another tenant
        exists (see aegis.tenancy.rbac)."""
        query = select(AgentRun).where(AgentRun.id == run_id)
        if tenant_id is not None:
            query = query.where(AgentRun.tenant_id == tenant_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def replay(self, run_id: uuid.UUID, tenant_id: str | None = None) -> ReplayedRun:
        run = await self.get_run(run_id, tenant_id=tenant_id)
        if run is None:
            raise ValueError(f"no such run: {run_id}")

        result = await self._session.execute(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_index)
        )
        steps = [
            StepRecord(
                step_type=s.step_type,
                input=s.input,
                output=s.output,
                error=s.error,
                provider_name=s.provider_name,
                model=s.model,
                tool_name=s.tool_name,
                input_tokens=s.input_tokens,
                output_tokens=s.output_tokens,
                retry_count=s.retry_count,
                duration_ms=s.duration_ms,
            )
            for s in result.scalars().all()
        ]
        return ReplayedRun(
            run_id=run.id,
            status=run.status,
            final_output=run.final_output,
            total_input_tokens=run.total_input_tokens,
            total_output_tokens=run.total_output_tokens,
            steps=steps,
        )
