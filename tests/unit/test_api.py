"""End-to-end wiring test: config -> providers -> router -> HTTP routes.

Does not require a running Ollama: LocalProvider's httpx client is only
touched on an actual chat call, so the unreachable-provider path itself is
what we assert on here (503/502 mapping), without needing respx/mocks.
"""

from fastapi.testclient import TestClient

from aegis.main import create_app


def test_health_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_chat_completion_returns_502_when_local_provider_unreachable() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "tenant_id": "t-1",
                "messages": [{"role": "user", "content": "hi"}],
                "data_classification": "confidential",
            },
        )
    # Ollama is very unlikely to be listening on localhost:11434 while running
    # the test suite in CI/offline — either way the router must surface a
    # clean 502/503, never leak a raw connection traceback.
    assert resp.status_code in (502, 503)
