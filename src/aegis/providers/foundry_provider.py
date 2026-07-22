"""FoundryProvider — integration with Azure AI Foundry / Azure OpenAI.

Same contract-testing-only rule as BedrockProvider (see
docs/adr/0003-local-first-contract-testing.md): this class is never invoked
against a real Azure subscription in this repository. It is exercised by unit
tests with an injected fake client and by contract tests replaying fixtures
under tests/contract/fixtures/foundry/*.json.

Uses the `openai` SDK's Azure client, which is the supported way to talk to
both Azure OpenAI and Azure AI Foundry model-as-a-service chat endpoints, plus
`azure-identity` for Managed Identity / AAD token auth (no API keys in prod).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    LLMProvider,
    ProviderAuthError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)

_ROLE_MAP = {
    Role.SYSTEM: "system",
    Role.USER: "user",
    Role.ASSISTANT: "assistant",
    Role.TOOL: "tool",
}


class FoundryProvider(LLMProvider):
    name = "foundry"

    def __init__(
        self,
        endpoint: str = "",
        api_version: str = "2024-10-21",
        client: Any | None = None,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self._endpoint = endpoint
        self._api_version = api_version
        self._client = client
        self._embedding_model = embedding_model

    def _get_client(self) -> Any:
        if self._client is None:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            from openai import AsyncAzureOpenAI

            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self._endpoint,
                azure_ad_token_provider=token_provider,
                api_version=self._api_version,
            )
        return self._client

    @staticmethod
    def _to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        return [{"role": _ROLE_MAP[m.role], "content": m.content} for m in messages]

    @staticmethod
    def _to_openai_tools(request: ChatRequest) -> list[dict[str, Any]] | None:
        if not request.tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]

    def _handle_error(self, exc: Exception) -> None:
        import openai

        if isinstance(exc, openai.APITimeoutError):
            raise ProviderTimeoutError(str(exc)) from exc
        if isinstance(exc, openai.AuthenticationError):
            raise ProviderAuthError(str(exc)) from exc
        retryable = (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)
        if isinstance(exc, retryable):
            raise ProviderUnavailableError(str(exc)) from exc
        raise ProviderUnavailableError(str(exc)) from exc

    async def chat(self, request: ChatRequest) -> ChatResponse:
        client = self._get_client()
        tools = self._to_openai_tools(request)
        try:
            kwargs: dict[str, Any] = dict(
                model=request.model,
                messages=self._to_openai_messages(request.messages),
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
            )
            if tools:
                kwargs["tools"] = tools
            completion = await client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)
            raise

        choice = completion.choices[0]
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=_safe_json_loads(tc.function.arguments),
            )
            for tc in (choice.message.tool_calls or [])
        ]
        return ChatResponse(
            message=ChatMessage(role=Role.ASSISTANT, content=choice.message.content or ""),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                output_tokens=completion.usage.completion_tokens if completion.usage else 0,
            ),
            provider_name=self.name,
            model=request.model,
            finish_reason=choice.finish_reason or "stop",
            raw=completion.model_dump(),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        tools = self._to_openai_tools(request)
        try:
            kwargs: dict[str, Any] = dict(
                model=request.model,
                messages=self._to_openai_messages(request.messages),
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            if tools:
                kwargs["tools"] = tools
            stream = await client.chat.completions.create(**kwargs)
            async for event in stream:
                if event.usage:
                    yield StreamChunk(
                        delta="",
                        usage=Usage(
                            input_tokens=event.usage.prompt_tokens,
                            output_tokens=event.usage.completion_tokens,
                        ),
                    )
                    continue
                choice = event.choices[0] if event.choices else None
                if choice is None:
                    continue
                delta = choice.delta.content or ""
                yield StreamChunk(delta=delta, finish_reason=choice.finish_reason)
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        client = self._get_client()
        try:
            resp = await client.embeddings.create(
                model=request.model or self._embedding_model, input=request.inputs
            )
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)
            raise

        return EmbedResponse(
            vectors=[d.embedding for d in resp.data],
            usage=Usage(input_tokens=resp.usage.prompt_tokens if resp.usage else 0),
            provider_name=self.name,
            model=request.model or self._embedding_model,
        )

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await asyncio.wait_for(client.models.list(), timeout=3.0)
            return True
        except Exception:  # noqa: BLE001
            return False


def _safe_json_loads(raw: str) -> dict[str, Any]:
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
