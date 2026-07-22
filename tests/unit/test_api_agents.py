"""API-level test for /v1/agents/*, using an in-memory SQLite session in
place of the real Postgres dependency, so this test needs no external
services running (see conftest-less dependency override below)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from aegis.db.base import Base
from aegis.db.session import get_session
from aegis.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    # StaticPool: a bare `:memory:` SQLite DB is otherwise per-connection, so
    # without it each request would see a fresh, empty database.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    with TestClient(app) as c:
        yield c
    await engine.dispose()


def test_run_agent_reports_failed_status_when_local_provider_unreachable(client) -> None:
    # No Ollama listening on localhost:11434 in this test environment — the
    # runtime must surface a clean "failed" run, not a 500 or a raw traceback.
    resp = client.post(
        "/v1/agents/run",
        json={"tenant_id": "t-1", "user_message": "hi", "data_classification": "confidential"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["final_output"] is None


def test_get_unknown_run_returns_404(client) -> None:
    resp = client.get(f"/v1/agents/runs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_run_after_failed_run_returns_its_trace(client) -> None:
    created = client.post(
        "/v1/agents/run",
        json={"tenant_id": "t-1", "user_message": "hi", "data_classification": "confidential"},
    ).json()

    resp = client.get(f"/v1/agents/runs/{created['run_id']}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["step_type"] == "llm_call"


def test_metrics_endpoint_is_prometheus_text_format(client) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
