"""API-level test for /v1/agents/*, using an in-memory SQLite session in
place of the real Postgres dependency, so this test needs no external
services running. Auth uses a real API key minted via ApiKeyStore against
that same in-memory DB — this exercises the actual RBAC dependency, not a
bypass of it."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from aegis.db.base import Base
from aegis.db.session import get_session
from aegis.main import create_app
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role

TENANT_ID = "acme-support"  # must match an entry in policies/tenants.yaml


@pytest.fixture
async def client_and_session():
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

    async with session_factory() as seed_session:
        dev_key_id, dev_secret = await ApiKeyStore(seed_session).create(TENANT_ID, Role.DEVELOPER)
        viewer_key_id, viewer_secret = await ApiKeyStore(seed_session).create(
            TENANT_ID, Role.VIEWER
        )
        await seed_session.commit()

    with TestClient(app) as c:
        yield c, f"{dev_key_id}.{dev_secret}", f"{viewer_key_id}.{viewer_secret}"
    await engine.dispose()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_run_agent_requires_authentication(client_and_session) -> None:
    client, _dev_token, _viewer_token = client_and_session
    resp = client.post("/v1/agents/run", json={"user_message": "hi"})
    assert resp.status_code == 401


def test_run_agent_reports_failed_status_when_local_provider_unreachable(
    client_and_session,
) -> None:
    # No Ollama listening on localhost:11434 in this test environment — the
    # runtime must surface a clean "failed" run, not a 500 or a raw traceback.
    client, dev_token, _viewer_token = client_and_session
    resp = client.post(
        "/v1/agents/run",
        json={"user_message": "hi", "data_classification": "confidential"},
        headers=_auth(dev_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["final_output"] is None


def test_viewer_role_cannot_trigger_a_run(client_and_session) -> None:
    client, _dev_token, viewer_token = client_and_session
    resp = client.post(
        "/v1/agents/run", json={"user_message": "hi"}, headers=_auth(viewer_token)
    )
    assert resp.status_code == 403


def test_get_unknown_run_returns_404(client_and_session) -> None:
    client, _dev_token, viewer_token = client_and_session
    resp = client.get(f"/v1/agents/runs/{uuid.uuid4()}", headers=_auth(viewer_token))
    assert resp.status_code == 404


def test_viewer_can_read_own_tenants_run_trace(client_and_session) -> None:
    client, dev_token, viewer_token = client_and_session
    created = client.post(
        "/v1/agents/run",
        json={"user_message": "hi", "data_classification": "confidential"},
        headers=_auth(dev_token),
    ).json()

    resp = client.get(f"/v1/agents/runs/{created['run_id']}", headers=_auth(viewer_token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert len(body["steps"]) == 1
    assert body["steps"][0]["step_type"] == "llm_call"


def test_list_runs_returns_recent_runs_for_the_caller_tenant(client_and_session) -> None:
    client, dev_token, viewer_token = client_and_session
    created = client.post(
        "/v1/agents/run",
        json={"user_message": "hi", "data_classification": "confidential"},
        headers=_auth(dev_token),
    ).json()

    resp = client.get("/v1/agents/runs", headers=_auth(viewer_token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["run_id"] == created["run_id"]
    assert body[0]["status"] == "failed"


def test_list_runs_requires_authentication(client_and_session) -> None:
    client, _dev_token, _viewer_token = client_and_session
    resp = client.get("/v1/agents/runs")
    assert resp.status_code == 401


def test_metrics_endpoint_is_prometheus_text_format(client_and_session) -> None:
    client, _dev_token, _viewer_token = client_and_session
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
