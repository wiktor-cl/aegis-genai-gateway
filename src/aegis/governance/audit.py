"""Append-only audit log. Records who, when, which model, how many tokens,
and which guardrail policy fired — one row per governed action. See
`aegis.db.models.AuditLogEntry` for the "insert-only, never update/delete"
contract this store deliberately keeps to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.db.models import AuditLogEntry


class AuditStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        tenant_id: str,
        action: str,
        actor: str = "system",
        run_id: uuid.UUID | None = None,
        provider_name: str | None = None,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        policy_rule: str | None = None,
        policy_action: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        entry = AuditLogEntry(
            tenant_id=tenant_id,
            run_id=run_id,
            actor=actor,
            action=action,
            provider_name=provider_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            policy_rule=policy_rule,
            policy_action=policy_action,
            detail=detail,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry.id

    async def for_tenant(
        self, tenant_id: str, since: datetime | None = None, limit: int = 100
    ) -> list[AuditLogEntry]:
        query = select(AuditLogEntry).where(AuditLogEntry.tenant_id == tenant_id)
        if since is not None:
            query = query.where(AuditLogEntry.created_at >= since)
        query = query.order_by(AuditLogEntry.created_at.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())


def utcnow() -> datetime:
    return datetime.now(UTC)
