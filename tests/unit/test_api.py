"""End-to-end wiring test: config -> providers -> router -> HTTP routes.

Does not require a running Ollama: LocalProvider's httpx client is only
touched on an actual chat call, so the unreachable-provider path itself is
what we assert on here (503/502 mapping), without needing respx/mocks.
"""

from fastapi.testclient import TestClient

from aegis.main import create_app
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role
from tests.unit.conftest import auth_header


def test_health_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_completion_requires_authentication(app_client) -> None:
    client, _session_factory = app_client
    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 401


async def test_chat_completion_returns_502_when_local_provider_unreachable(app_client) -> None:
    client, session_factory = app_client
    async with session_factory() as session:
        key_id, secret = await ApiKeyStore(session).create("acme-support", Role.DEVELOPER)
        await session.commit()

    # Ollama is very unlikely to be listening on localhost:11434 while running
    # the test suite in CI/offline — either way the router must surface a
    # clean 502/503, never leak a raw connection traceback.
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "data_classification": "confidential",
        },
        headers=auth_header(f"{key_id}.{secret}"),
    )
    assert resp.status_code in (502, 503)
