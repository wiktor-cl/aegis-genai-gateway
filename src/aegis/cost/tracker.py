"""Per-tenant/per-run cost tracking, backed by the `cost_entries` table.

Every provider call (real or simulated-cloud) should produce exactly one
`CostEntry` via `record()`. `month_to_date_usd()` is the read side used by
`BudgetEnforcer` and the cost-reporting API endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.cost.pricing import PricingTable
from aegis.db.models import CostEntry


class CostTracker:
    def __init__(self, session: AsyncSession, pricing: PricingTable) -> None:
        self._session = session
        self._pricing = pricing

    async def record(
        self,
        tenant_id: str,
        provider_name: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        run_id: uuid.UUID | None = None,
    ) -> float:
        cost_usd = self._pricing.estimate_cost_usd(
            provider_name, model, input_tokens, output_tokens
        )
        entry = CostEntry(
            tenant_id=tenant_id,
            run_id=run_id,
            provider_name=provider_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        self._session.add(entry)
        await self._session.flush()
        return cost_usd

    async def month_to_date_usd(self, tenant_id: str, as_of: datetime | None = None) -> float:
        as_of = as_of or datetime.now(UTC)
        start_of_month = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        result = await self._session.execute(
            select(func.coalesce(func.sum(CostEntry.cost_usd), 0.0)).where(
                CostEntry.tenant_id == tenant_id, CostEntry.created_at >= start_of_month
            )
        )
        return float(result.scalar_one())
