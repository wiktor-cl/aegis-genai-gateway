"""LocalProvider — the only provider actually invoked over the network at runtime.

Talks to a local Ollama instance (default http://localhost:11434). No cloud
credentials, no egress, no cost. This is the default provider for the whole
project (see docs/adr/0001-provider-abstraction-layer.md and
docs/adr/0003-local-first-contract-testing.md).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import httpx

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
    ToolSpec,
    Usage,
)


def _ollama_tools_payload(tools: list[ToolSpec]) -> list[dict] | None:
    """Ollama's /api/chat `tools` field mirrors OpenAI's function-calling
    shape. Omitted entirely (not an empty list) when there are no tools —
    some model chat templates behave differently when `tools: []` is present
    at all versus genuinely absent."""
    if not tools:
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
        for t in tools
    ]


def _parse_ollama_tool_calls(message: dict) -> list[ToolCall]:
    """Ollama includes an `id` per call as of recent versions, but earlier
    ones may not — synthesize one from the index so `ToolCall.id` (required)
    is always populated either way."""
    calls = message.get("tool_calls") or []
    parsed: list[ToolCall] = []
    for i, call in enumerate(calls):
        function = call.get("function", {})
        parsed.append(
            ToolCall(
                id=call.get("id") or f"call-{i}",
                name=function.get("name", ""),
                arguments=function.get("arguments") or {},
            )
        )
    return parsed


def _raise_for_ollama_status(resp: httpx.Response) -> None:
    """Every non-2xx from Ollama must become a `ProviderError` subtype, never
    a raw `httpx.HTTPStatusError` — otherwise it reaches the API layer
    unhandled as a raw 500 (see docs/threat-model.md I5). A 404 here usually
    just means the model named in `policies/routing.yaml` hasn't been
    `ollama pull`ed yet — the single most likely first-run mistake for
    anyone cloning this repo, so it must fail cleanly, not with a traceback.
    """
    if resp.status_code < 400:
        return
    if resp.status_code in (401, 403):
        raise ProviderAuthError(f"Ollama returned {resp.status_code}")
    raise ProviderUnavailableError(
        f"Ollama returned {resp.status_code}: {resp.text[:200]!r} "
        "— is the model pulled? see `ollama pull <model>` in README"
    )


class LocalProvider(LLMProvider):
    name = "local"

    def __init__(self, base_url: str = "http://localhost:11434", timeout_s: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    async def chat(self, request: ChatRequest) -> ChatResponse:
        payload: dict = {
            "model": request.model,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in request.messages
            ],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        tools_payload = _ollama_tools_payload(request.tools)
        if tools_payload is not None:
            payload["tools"] = tools_payload

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"local provider timed out after {self._timeout_s}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                f"cannot reach Ollama at {self._base_url} — is `ollama serve` running?"
            ) from exc

        _raise_for_ollama_status(resp)
        body = resp.json()

        message = body.get("message", {})
        content = message.get("content", "")
        tool_calls = _parse_ollama_tool_calls(message)
        usage = Usage(
            input_tokens=body.get("prompt_eval_count", 0),
            output_tokens=body.get("eval_count", 0),
        )
        _ = time.monotonic() - started  # surfaced via observability middleware, not here
        return ChatResponse(
            message=ChatMessage(role=Role.ASSISTANT, content=content),
            tool_calls=tool_calls,
            usage=usage,
            provider_name=self.name,
            model=request.model,
            finish_reason=(
                "tool_use" if tool_calls else ("stop" if body.get("done", True) else "length")
            ),
            raw=body,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": request.model,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in request.messages
            ],
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client, client.stream(
                "POST", f"{self._base_url}/api/chat", json=payload
            ) as resp:
                _raise_for_ollama_status(resp)
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    import json

                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)
                    yield StreamChunk(
                        delta=delta,
                        finish_reason="stop" if done else None,
                        usage=(
                            Usage(
                                input_tokens=chunk.get("prompt_eval_count", 0),
                                output_tokens=chunk.get("eval_count", 0),
                            )
                            if done
                            else None
                        ),
                    )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"local provider timed out after {self._timeout_s}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                f"cannot reach Ollama at {self._base_url} — is `ollama serve` running?"
            ) from exc

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        vectors: list[list[float]] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                for text in request.inputs:
                    resp = await client.post(
                        f"{self._base_url}/api/embeddings",
                        json={"model": request.model, "prompt": text},
                    )
                    _raise_for_ollama_status(resp)
                    vectors.append(resp.json()["embedding"])
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"local provider timed out after {self._timeout_s}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                f"cannot reach Ollama at {self._base_url} — is `ollama serve` running?"
            ) from exc

        return EmbedResponse(
            vectors=vectors,
            usage=Usage(input_tokens=sum(len(t.split()) for t in request.inputs)),
            provider_name=self.name,
            model=request.model,
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
