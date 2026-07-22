"""Cost reporting: month-to-date spend vs. the tenant's monthly budget.

A developer/viewer can only ever see their own tenant's report — the
`tenant_id` query param is only honored for `Role.ADMIN` (see
aegis.tenancy.rbac); anyone else attempting to pass a different tenant_id
gets a 403, not silently-scoped-down data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.cost.budgets import BudgetEnforcer
from aegis.cost.tracker import CostTracker
from aegis.db.session import get_session
from aegis.tenancy.models import Role
from aegis.tenancy.rbac import Principal, require_role

router = APIRouter(prefix="/v1/cost", tags=["cost"])


class CostReportOut(BaseModel):
    tenant_id: str
    month_to_date_usd: float
    monthly_budget_usd: float
    percent_used: float
    status: str


@router.get("/report", response_model=CostReportOut)
async def get_cost_report(
    request: Request,
    tenant_id: str | None = None,
    principal: Principal = Depends(require_role(Role.VIEWER)),
    session: AsyncSession = Depends(get_session),
) -> CostReportOut:
    target_tenant = tenant_id or principal.tenant_id
    if principal.role != Role.ADMIN and target_tenant != principal.tenant_id:
        raise HTTPException(status_code=403, detail="cannot view another tenant's cost report")

    tenant = request.app.state.tenants.get(target_tenant)
    if tenant is None:
        raise HTTPException(status_code=404, detail=f"unknown tenant: {target_tenant}")

    tracker = CostTracker(session, request.app.state.pricing)
    enforcer = BudgetEnforcer(tracker)
    result = await enforcer.check(target_tenant, tenant.monthly_budget_usd)

    return CostReportOut(
        tenant_id=target_tenant,
        month_to_date_usd=result.month_to_date_usd,
        monthly_budget_usd=result.monthly_budget_usd,
        percent_used=result.percent_used,
        status=result.status.value,
    )
