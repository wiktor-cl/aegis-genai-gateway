"""Contract tests: FoundryProvider against recorded Azure OpenAI-shaped responses.

No Azure subscription, no network call — `FakeAzureOpenAIClient` is injected in
place of `openai.AsyncAzureOpenAI`. Fixtures are validated into the real
`openai` SDK response models so a schema drift in the SDK itself would show up
here too. See docs/adr/0003-local-first-contract-testing.md.
"""

import json
from pathlib import Path

import pytest
from openai import APIConnectionError, AuthenticationError
from openai.types import CreateEmbeddingResponse
from openai.types.chat import ChatCompletion

from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    EmbedRequest,
    ProviderAuthError,
    ProviderUnavailableError,
    Role,
)
from aegis.providers.foundry_provider import FoundryProvider
from tests.contract.fakes import FakeAzureOpenAIClient

FIXTURES = Path(__file__).parent / "fixtures" / "foundry"
pytestmark = pytest.mark.contract


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _request(text: str = "What is the capital of France?") -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role=Role.USER, content=text)],
        model="gpt-4o",
        tenant_id="t-1",
        request_id="r-1",
    )


async def test_chat_parses_basic_completion() -> None:
    completion = ChatCompletion.model_validate(load("chat_completion_basic.json"))
    fake = FakeAzureOpenAIClient(chat_response=completion)
    provider = FoundryProvider(endpoint="https://fake.example.com", client=fake)

    response = await provider.chat(_request())

    assert response.message.content == "The capital of France is Paris."
    assert response.provider_name == "foundry"
    assert response.usage.input_tokens == 22
    assert response.usage.output_tokens == 8
    assert response.finish_reason == "stop"


async def test_chat_parses_tool_call_completion() -> None:
    completion = ChatCompletion.model_validate(load("chat_completion_tool_call.json"))
    fake = FakeAzureOpenAIClient(chat_response=completion)
    provider = FoundryProvider(endpoint="https://fake.example.com", client=fake)

    response = await provider.chat(_request("What is 12 * 7?"))

    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "calculator"
    assert call.arguments == {"expression": "12 * 7"}


async def test_embed_parses_embedding_response() -> None:
    embedding = CreateEmbeddingResponse.model_validate(load("embedding_basic.json"))
    fake = FakeAzureOpenAIClient(embedding_response=embedding)
    provider = FoundryProvider(endpoint="https://fake.example.com", client=fake)

    response = await provider.embed(
        EmbedRequest(
            inputs=["hello"], model="text-embedding-3-small", tenant_id="t-1", request_id="r-2"
        )
    )

    assert response.vectors == [[0.0012, -0.0341, 0.0872, 0.0154]]
    assert response.usage.input_tokens == 6


async def test_connection_error_maps_to_provider_unavailable() -> None:
    import httpx

    err = APIConnectionError(request=httpx.Request("POST", "https://fake.example.com"))
    fake = FakeAzureOpenAIClient(chat_error=err)
    provider = FoundryProvider(endpoint="https://fake.example.com", client=fake)

    with pytest.raises(ProviderUnavailableError):
        await provider.chat(_request())


async def test_authentication_error_maps_to_provider_auth_error() -> None:
    import httpx

    response = httpx.Response(401, request=httpx.Request("POST", "https://fake.example.com"))
    err = AuthenticationError(message="invalid api key", response=response, body=None)
    fake = FakeAzureOpenAIClient(chat_error=err)
    provider = FoundryProvider(endpoint="https://fake.example.com", client=fake)

    with pytest.raises(ProviderAuthError):
        await provider.chat(_request())
