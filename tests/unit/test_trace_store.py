import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.agent.trace import StepRecord, TraceStore
from aegis.db.base import Base


@pytest.fixture
async def trace_store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield TraceStore(session)
    await engine.dispose()


async def test_start_record_finish_and_get_run(trace_store) -> None:
    run_id = await trace_store.start_run(
        tenant_id="t-1", agent_name="demo", max_steps=5, token_budget=1000
    )
    await trace_store.record_step(
        run_id,
        0,
        StepRecord(
            step_type="llm_call",
            input={"x": 1},
            output={"y": 2},
            input_tokens=10,
            output_tokens=5,
        ),
    )
    await trace_store.finish_run(run_id, status="completed", final_output="done")

    run = await trace_store.get_run(run_id)
    assert run is not None
    assert run.status == "completed"
    assert run.final_output == "done"
    assert run.step_count == 1
    assert run.total_input_tokens == 10
    assert run.total_output_tokens == 5


async def test_replay_reconstructs_steps_in_order(trace_store) -> None:
    run_id = await trace_store.start_run(
        tenant_id="t-1", agent_name="demo", max_steps=5, token_budget=1000
    )
    await trace_store.record_step(run_id, 0, StepRecord(step_type="llm_call", input={"i": 0}))
    await trace_store.record_step(
        run_id, 1, StepRecord(step_type="tool_call", tool_name="calculator", input={"i": 1})
    )
    await trace_store.finish_run(run_id, status="completed", final_output="42")

    replayed = await trace_store.replay(run_id)

    assert replayed.status == "completed"
    assert replayed.final_output == "42"
    assert [s.input["i"] for s in replayed.steps] == [0, 1]
    assert replayed.steps[1].tool_name == "calculator"


async def test_replay_unknown_run_raises(trace_store) -> None:
    with pytest.raises(ValueError):
        await trace_store.replay(uuid.uuid4())
