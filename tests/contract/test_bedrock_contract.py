"""Contract tests: BedrockProvider against recorded Bedrock Converse API shapes.

No AWS account, no network call, no boto3 credentials resolution — the
`FakeBedrockRuntimeClient` is injected in place of the real boto3 client. See
docs/adr/0003-local-first-contract-testing.md.
"""

import json
from pathlib import Path

import pytest

from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    ProviderAuthError,
    ProviderUnavailableError,
    Role,
)
from aegis.providers.bedrock_provider import BedrockProvider
from tests.contract.fakes import FakeBedrockRuntimeClient

FIXTURES = Path(__file__).parent / "fixtures" / "bedrock"
pytestmark = pytest.mark.contract


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _request(text: str = "What is the capital of France?") -> ChatRequest:
    return ChatRequest(
        messages=[ChatMessage(role=Role.USER, content=text)],
        model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        tenant_id="t-1",
        request_id="r-1",
    )


async def test_chat_parses_basic_converse_response() -> None:
    fake = FakeBedrockRuntimeClient(converse_response=load("converse_basic.json"))
    provider = BedrockProvider(client=fake)

    response = await provider.chat(_request())

    assert response.message.content == "The capital of France is Paris."
    assert response.provider_name == "bedrock"
    assert response.usage.input_tokens == 24
    assert response.usage.output_tokens == 9
    assert response.finish_reason == "end_turn"
    assert response.tool_calls == []


async def test_chat_parses_tool_use_response() -> None:
    fake = FakeBedrockRuntimeClient(converse_response=load("converse_tool_use.json"))
    provider = BedrockProvider(client=fake)

    response = await provider.chat(_request("What is 12 * 7?"))

    assert response.finish_reason == "tool_use"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.name == "calculator"
    assert call.arguments == {"expression": "12 * 7"}
    assert call.id == "tooluse_9f1c2b3a"


async def test_throttling_error_maps_to_provider_unavailable_not_raw_boto_error() -> None:
    fake = FakeBedrockRuntimeClient(converse_error=load("converse_throttled_error.json"))
    provider = BedrockProvider(client=fake)

    with pytest.raises(ProviderUnavailableError):
        await provider.chat(_request())


async def test_auth_error_maps_to_provider_auth_error_and_is_distinguishable() -> None:
    access_denied = {
        "Error": {"Code": "AccessDeniedException", "Message": "not authorized"},
        "ResponseMetadata": {"HTTPStatusCode": 403},
    }
    fake = FakeBedrockRuntimeClient(converse_error=access_denied)
    provider = BedrockProvider(client=fake)

    with pytest.raises(ProviderAuthError):
        await provider.chat(_request())
