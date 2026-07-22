from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.cost.budgets import BudgetEnforcer, BudgetStatus
from aegis.cost.pricing import PricingTable
from aegis.cost.tracker import CostTracker
from aegis.db.base import Base

PRICING_YAML = Path(__file__).resolve().parents[2] / "policies" / "pricing.yaml"


@pytest.fixture
async def tracker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    pricing = PricingTable.from_yaml(PRICING_YAML)
    async with session_factory() as session:
        yield CostTracker(session, pricing)
    await engine.dispose()


async def test_record_and_month_to_date(tracker) -> None:
    await tracker.record("t-1", "bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 1000)
    await tracker.record("t-1", "bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 1000)

    total = await tracker.month_to_date_usd("t-1")
    assert total == pytest.approx(2 * (0.003 + 0.015))


async def test_costs_are_isolated_per_tenant(tracker) -> None:
    await tracker.record("t-1", "bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 1000)
    await tracker.record("t-2", "bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 1000)

    assert await tracker.month_to_date_usd("t-1") == pytest.approx(0.018)
    assert await tracker.month_to_date_usd("t-2") == pytest.approx(0.018)


async def test_budget_status_ok_below_threshold(tracker) -> None:
    await tracker.record("t-1", "local", "llama3.1:8b", 1000, 1000)
    enforcer = BudgetEnforcer(tracker)
    result = await enforcer.check("t-1", monthly_budget_usd=100.0)
    assert result.status == BudgetStatus.OK


async def test_budget_status_soft_alert_at_80_percent(tracker) -> None:
    await tracker.record("t-1", "bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 1000)
    enforcer = BudgetEnforcer(tracker)
    # spend is 0.018; budget 0.02 -> 90% used
    result = await enforcer.check("t-1", monthly_budget_usd=0.02)
    assert result.status == BudgetStatus.SOFT_ALERT


async def test_budget_status_hard_stop_at_100_percent(tracker) -> None:
    await tracker.record("t-1", "bedrock", "anthropic.claude-3-5-sonnet-20241022-v2:0", 1000, 1000)
    enforcer = BudgetEnforcer(tracker)
    result = await enforcer.check("t-1", monthly_budget_usd=0.01)
    assert result.status == BudgetStatus.HARD_STOP
