"""BedrockProvider — full boto3 integration against AWS Bedrock's Converse API.

IMPORTANT (see docs/adr/0003-local-first-contract-testing.md): this class is
never invoked against a real AWS account in this repository. It is exercised
exclusively by:
  - unit tests using a `FakeBedrockRuntimeClient` that implements the same
    boto3 client surface (`converse`, `converse_stream`, `invoke_model`), and
  - contract tests replaying recorded fixtures under
    tests/contract/fixtures/bedrock/*.json.

The code is production-shaped (real boto3 client, real error handling) so it
is reviewable and deployable as-is by a team with an actual AWS account and
budget — it is simply never exercised against one here.
"""

from __future__ import annotations

import asyncio
import json
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

_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelTimeoutException",
}
_AUTH_ERROR_CODES = {
    "AccessDeniedException",
    "UnrecognizedClientException",
    "ExpiredTokenException",
}


class BedrockProvider(LLMProvider):
    name = "bedrock"

    def __init__(
        self,
        region_name: str = "us-east-1",
        client: Any | None = None,
        embedding_model_id: str = "amazon.titan-embed-text-v2:0",
    ) -> None:
        """`client` is injected in tests (fake or a moto-backed boto3 client).

        In production it is a real `boto3.client("bedrock-runtime", ...)`,
        constructed lazily so importing this module never touches botocore
        credential resolution (which would fail loudly in this offline repo).
        """
        self._region_name = region_name
        self._client = client
        self._embedding_model_id = embedding_model_id

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # local import: keep boto3 optional at module-import time

            self._client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self._client

    @staticmethod
    def _to_bedrock_messages(messages: list[ChatMessage]) -> tuple[list[dict], list[dict]]:
        system: list[dict] = []
        converted: list[dict] = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system.append({"text": m.content})
            else:
                role = "user" if m.role == Role.USER else "assistant"
                converted.append({"role": role, "content": [{"text": m.content}]})
        return system, converted

    @staticmethod
    def _to_bedrock_tool_config(request: ChatRequest) -> dict | None:
        if not request.tools:
            return None
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": {"json": t.parameters},
                    }
                }
                for t in request.tools
            ]
        }

    def _handle_client_error(self, exc: Exception) -> None:
        from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

        if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
            raise ProviderTimeoutError(str(exc)) from exc
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _AUTH_ERROR_CODES:
                raise ProviderAuthError(f"Bedrock auth error: {code}") from exc
            if code in _RETRYABLE_ERROR_CODES:
                raise ProviderUnavailableError(f"Bedrock transient error: {code}") from exc
            raise ProviderUnavailableError(f"Bedrock error: {code}") from exc
        raise ProviderUnavailableError(str(exc)) from exc

    async def chat(self, request: ChatRequest) -> ChatResponse:
        system, messages = self._to_bedrock_messages(request.messages)
        tool_config = self._to_bedrock_tool_config(request)
        client = self._get_client()

        def _call() -> dict:
            kwargs: dict[str, Any] = dict(
                modelId=request.model,
                messages=messages,
                inferenceConfig={
                    "temperature": request.temperature,
                    "maxTokens": request.max_output_tokens,
                },
            )
            if system:
                kwargs["system"] = system
            if tool_config:
                kwargs["toolConfig"] = tool_config
            return client.converse(**kwargs)

        try:
            body = await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001 — normalized below
            self._handle_client_error(exc)
            raise  # unreachable, _handle_client_error always raises

        output_message = body["output"]["message"]
        text_parts = [c["text"] for c in output_message.get("content", []) if "text" in c]
        tool_calls = [
            ToolCall(
                id=c["toolUse"]["toolUseId"],
                name=c["toolUse"]["name"],
                arguments=c["toolUse"]["input"],
            )
            for c in output_message.get("content", [])
            if "toolUse" in c
        ]
        usage = body.get("usage", {})
        return ChatResponse(
            message=ChatMessage(role=Role.ASSISTANT, content="".join(text_parts)),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=usage.get("inputTokens", 0),
                output_tokens=usage.get("outputTokens", 0),
            ),
            provider_name=self.name,
            model=request.model,
            finish_reason=body.get("stopReason", "stop"),
            raw=body,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        system, messages = self._to_bedrock_messages(request.messages)
        tool_config = self._to_bedrock_tool_config(request)
        client = self._get_client()

        def _call() -> dict:
            kwargs: dict[str, Any] = dict(
                modelId=request.model,
                messages=messages,
                inferenceConfig={
                    "temperature": request.temperature,
                    "maxTokens": request.max_output_tokens,
                },
            )
            if system:
                kwargs["system"] = system
            if tool_config:
                kwargs["toolConfig"] = tool_config
            return client.converse_stream(**kwargs)

        try:
            response = await asyncio.to_thread(_call)
            for event in response["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"].get("text", "")
                    yield StreamChunk(delta=delta)
                elif "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason", "stop")
                    yield StreamChunk(delta="", finish_reason=stop_reason)
                elif "metadata" in event:
                    usage = event["metadata"].get("usage", {})
                    yield StreamChunk(
                        delta="",
                        usage=Usage(
                            input_tokens=usage.get("inputTokens", 0),
                            output_tokens=usage.get("outputTokens", 0),
                        ),
                    )
        except Exception as exc:  # noqa: BLE001
            self._handle_client_error(exc)

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        client = self._get_client()

        def _call_one(text: str) -> dict:
            resp = client.invoke_model(
                modelId=request.model or self._embedding_model_id,
                body=json.dumps({"inputText": text}),
            )
            return json.loads(resp["body"].read())

        try:
            tasks = (asyncio.to_thread(_call_one, t) for t in request.inputs)
            bodies = await asyncio.gather(*tasks)
        except Exception as exc:  # noqa: BLE001
            self._handle_client_error(exc)
            raise

        return EmbedResponse(
            vectors=[b["embedding"] for b in bodies],
            usage=Usage(input_tokens=sum(b.get("inputTextTokenCount", 0) for b in bodies)),
            provider_name=self.name,
            model=request.model or self._embedding_model_id,
        )

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            await asyncio.to_thread(client.list_foundation_models, byOutputModality="TEXT")
            return True
        except Exception:  # noqa: BLE001 — health check must never raise
            return False
