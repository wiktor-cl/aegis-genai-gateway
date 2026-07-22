"""Agent run/step persistence — the "full trace of every run" requirement.

A run's steps are stored with their full input/output payloads, which is
what makes `AgentRuntime.replay()` (src/aegis/agent/runtime.py) possible:
replay reads the stored LLM responses and tool results back in order instead
of calling providers/tools again, so a run is deterministically reproducible
from the database alone.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aegis.db.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(index=True)
    agent_name: Mapped[str]
    status: Mapped[str] = mapped_column(default="running")
    """running | completed | failed | budget_exceeded | max_steps_exceeded"""

    data_classification: Mapped[str] = mapped_column(default="internal")
    cost_tier: Mapped[str] = mapped_column(default="standard")

    max_steps: Mapped[int]
    token_budget: Mapped[int]
    total_input_tokens: Mapped[int] = mapped_column(default=0)
    total_output_tokens: Mapped[int] = mapped_column(default=0)
    step_count: Mapped[int] = mapped_column(default=0)

    final_output: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", order_by="AgentStep.step_index", cascade="all, delete-orphan"
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    step_index: Mapped[int]
    step_type: Mapped[str]
    """llm_call | tool_call"""

    provider_name: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    tool_name: Mapped[str | None] = mapped_column(default=None)

    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    duration_ms: Mapped[int | None] = mapped_column(default=None)

    run: Mapped[AgentRun] = relationship(back_populates="steps")
