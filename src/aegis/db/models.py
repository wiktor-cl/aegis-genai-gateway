"""Agent run/step persistence — the "full trace of every run" requirement.

A run's steps are stored with their full input/output payloads, which is
what makes `AgentRuntime.replay()` (src/aegis/agent/runtime.py) possible:
replay reads the stored LLM responses and tool results back in order instead
of calling providers/tools again, so a run is deterministically reproducible
from the database alone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(UTC)
    )
    """Python-side `default` (not just `server_default`) so ordering by this
    column (see `TraceStore.list_runs`) has real precision even on SQLite,
    whose `CURRENT_TIMESTAMP` is second-granularity — two runs started within
    the same second would otherwise sort arbitrarily."""
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


class AuditLogEntry(Base):
    """Append-only: this module never updates or deletes a row, only inserts
    (see aegis.governance.audit.AuditStore). A real deployment should also
    enforce this at the database role level (INSERT-only grant), not just in
    application code — see docs/threat-model.md.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    actor: Mapped[str] = mapped_column(default="system")
    action: Mapped[str]
    """chat_completion | agent_run | guardrail_redact | guardrail_block | ..."""

    provider_name: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    policy_rule: Mapped[str | None] = mapped_column(default=None)
    policy_action: Mapped[str | None] = mapped_column(default=None)
    detail: Mapped[dict | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class CostEntry(Base):
    __tablename__ = "cost_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    provider_name: Mapped[str]
    model: Mapped[str]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cost_usd: Mapped[float]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ApiKey(Base):
    """API key rotation model: rotating a key revokes it and inserts a new
    row with `rotated_from` pointing at the old key's id, so the audit trail
    of "which key was active when" is never lost.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key_id: Mapped[str] = mapped_column(unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(index=True)
    role: Mapped[str]
    """admin | developer | viewer"""
    hashed_secret: Mapped[str]
    rotated_from: Mapped[uuid.UUID | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
