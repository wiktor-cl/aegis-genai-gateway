"""LocalProvider unit tests. httpx calls to Ollama are mocked with respx —
no real Ollama instance needs to be running for these to pass. The one place
LocalProvider is exercised against a *real* local Ollama server is
scripts/smoke_test_local_provider.py, run manually / in the offline
docker-compose stack, never in CI (CI has no GPU/model download budget)."""

import httpx
import pytest
import respx

from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    EmbedRequest,
    ProviderTimeoutError,
    ProviderUnavailableError,
    Role,
)
from aegis.providers.local_provider import LocalProvider

BASE_URL = "http://localhost:11434"


def _request() -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role=Role.USER, content="hello")],
        model="llama3.1:8b",
        tenant_id="t-1",
        request_id="r-1",
    )


@respx.mock
async def test_chat_parses_ollama_response() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Hi there!"},
                "done": True,
                "prompt_eval_count": 5,
                "eval_count": 3,
            },
        )
    )
    provider = LocalProvider(base_url=BASE_URL)

    response = await provider.chat(_request())

    assert response.message.content == "Hi there!"
    assert response.provider_name == "local"
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens == 3


@respx.mock
async def test_chat_raises_provider_unavailable_when_ollama_not_running() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    provider = LocalProvider(base_url=BASE_URL)

    with pytest.raises(ProviderUnavailableError):
        await provider.chat(_request())


@respx.mock
async def test_chat_raises_provider_timeout() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(side_effect=httpx.TimeoutException("timed out"))
    provider = LocalProvider(base_url=BASE_URL)

    with pytest.raises(ProviderTimeoutError):
        await provider.chat(_request())


@respx.mock
async def test_chat_raises_provider_unavailable_on_5xx() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(return_value=httpx.Response(503))
    provider = LocalProvider(base_url=BASE_URL)

    with pytest.raises(ProviderUnavailableError):
        await provider.chat(_request())


@respx.mock
async def test_embed_parses_ollama_embedding_response() -> None:
    respx.post(f"{BASE_URL}/api/embeddings").mock(
        return_value=httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
    )
    provider = LocalProvider(base_url=BASE_URL)

    response = await provider.embed(
        EmbedRequest(
            inputs=["hello world"], model="nomic-embed-text", tenant_id="t-1", request_id="r-2"
        )
    )

    assert response.vectors == [[0.1, 0.2, 0.3]]
    assert response.provider_name == "local"


@respx.mock
async def test_health_check_true_when_ollama_reachable() -> None:
    respx.get(f"{BASE_URL}/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
    provider = LocalProvider(base_url=BASE_URL)

    assert await provider.health_check() is True


@respx.mock
async def test_health_check_false_when_ollama_unreachable() -> None:
    respx.get(f"{BASE_URL}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    provider = LocalProvider(base_url=BASE_URL)

    assert await provider.health_check() is False
