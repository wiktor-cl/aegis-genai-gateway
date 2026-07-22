"""LocalProvider unit tests. httpx calls to Ollama are mocked with respx —
no real Ollama instance needs to be running for these to pass. The one place
LocalProvider is exercised against a *real* local Ollama server is
scripts/smoke_test_local_provider.py, run manually / in the offline
docker-compose stack, never in CI (CI has no GPU/model download budget)."""

import json

import httpx
import pytest
import respx

from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    EmbedRequest,
    ProviderAuthError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    Role,
    ToolSpec,
)
from aegis.providers.local_provider import LocalProvider

BASE_URL = "http://localhost:11434"


def _request(tools: list[ToolSpec] | None = None) -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role=Role.USER, content="hello")],
        model="llama3.1:8b",
        tools=tools or [],
        tenant_id="t-1",
        request_id="r-1",
    )


_CALCULATOR_TOOL = ToolSpec(
    name="calculator",
    description="Evaluate an arithmetic expression.",
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
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
async def test_chat_sends_tool_definitions_when_tools_are_offered() -> None:
    # Regression test: LocalProvider used to silently drop request.tools —
    # the tool-calling loop could never actually work against a real Ollama
    # call, only against scripted providers in tests. See git history for
    # the incident this test locks in.
    route = respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"role": "assistant", "content": "no tool needed"}, "done": True}
        )
    )
    provider = LocalProvider(base_url=BASE_URL)

    await provider.chat(_request(tools=[_CALCULATOR_TOOL]))

    body = json.loads(route.calls[0].request.content)
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Evaluate an arithmetic expression.",
                "parameters": _CALCULATOR_TOOL.parameters,
            },
        }
    ]


@respx.mock
async def test_chat_omits_tools_field_when_no_tools_offered() -> None:
    route = respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"role": "assistant", "content": "hi"}, "done": True}
        )
    )
    provider = LocalProvider(base_url=BASE_URL)

    await provider.chat(_request())

    body = json.loads(route.calls[0].request.content)
    assert "tools" not in body


@respx.mock
async def test_chat_parses_tool_calls_from_ollama_response() -> None:
    # Real shape observed from a live `ollama run llama3.1:8b` tool call.
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_oyhkq87c",
                            "function": {
                                "index": 0,
                                "name": "calculator",
                                "arguments": {"expression": "6 * 7"},
                            },
                        }
                    ],
                },
                "done": True,
                "prompt_eval_count": 161,
                "eval_count": 19,
            },
        )
    )
    provider = LocalProvider(base_url=BASE_URL)

    response = await provider.chat(_request(tools=[_CALCULATOR_TOOL]))

    assert response.finish_reason == "tool_use"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call_oyhkq87c"
    assert call.name == "calculator"
    assert call.arguments == {"expression": "6 * 7"}


@respx.mock
async def test_chat_synthesizes_tool_call_id_when_ollama_omits_it() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "calculator", "arguments": {"expression": "1+1"}}}
                    ],
                },
                "done": True,
            },
        )
    )
    provider = LocalProvider(base_url=BASE_URL)

    response = await provider.chat(_request(tools=[_CALCULATOR_TOOL]))

    assert response.tool_calls[0].id == "call-0"


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
async def test_chat_raises_provider_unavailable_on_404_model_not_pulled() -> None:
    # The single most likely first-run mistake: the model in policies/routing.yaml
    # hasn't been `ollama pull`ed. Must become a clean ProviderError, not a raw
    # httpx.HTTPStatusError bubbling up as an unhandled 500 (see local_provider.py's
    # _raise_for_ollama_status and docs/threat-model.md I5).
    respx.post(f"{BASE_URL}/api/chat").mock(
        return_value=httpx.Response(404, text='{"error":"model \\"llama3.1:8b\\" not found"}')
    )
    provider = LocalProvider(base_url=BASE_URL)

    with pytest.raises(ProviderUnavailableError):
        await provider.chat(_request())


@respx.mock
async def test_chat_raises_provider_auth_error_on_401() -> None:
    respx.post(f"{BASE_URL}/api/chat").mock(return_value=httpx.Response(401))
    provider = LocalProvider(base_url=BASE_URL)

    with pytest.raises(ProviderAuthError):
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
