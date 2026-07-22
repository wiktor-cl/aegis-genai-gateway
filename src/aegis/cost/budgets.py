"""Monthly budget enforcement: soft alert at 80% (configurable), hard stop
at 100%. The hard stop is enforced by the caller checking `BudgetStatus` —
this module only computes status, it does not itself reject requests, so
callers (API routes, agent runtime) decide what "stopped" means for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from aegis.cost.tracker import CostTracker


class BudgetStatus(StrEnum):
    OK = "ok"
    SOFT_ALERT = "soft_alert"
    HARD_STOP = "hard_stop"


@dataclass
class BudgetCheckResult:
    status: BudgetStatus
    month_to_date_usd: float
    monthly_budget_usd: float
    percent_used: float


class BudgetEnforcer:
    def __init__(self, cost_tracker: CostTracker, soft_alert_threshold: float = 0.8) -> None:
        self._cost_tracker = cost_tracker
        self._soft_alert_threshold = soft_alert_threshold

    async def check(self, tenant_id: str, monthly_budget_usd: float) -> BudgetCheckResult:
        spent = await self._cost_tracker.month_to_date_usd(tenant_id)
        percent = spent / monthly_budget_usd if monthly_budget_usd > 0 else 0.0

        if percent >= 1.0:
            status = BudgetStatus.HARD_STOP
        elif percent >= self._soft_alert_threshold:
            status = BudgetStatus.SOFT_ALERT
        else:
            status = BudgetStatus.OK

        return BudgetCheckResult(
            status=status,
            month_to_date_usd=spent,
            monthly_budget_usd=monthly_budget_usd,
            percent_used=percent,
        )
