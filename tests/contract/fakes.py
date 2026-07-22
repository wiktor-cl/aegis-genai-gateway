"""Fakes implementing the same call surface as the real boto3/openai clients.

Used exclusively by contract tests (tests/contract/test_*_contract.py) so
BedrockProvider/FoundryProvider parsing logic is exercised against
realistic response/error shapes without any network access. See
docs/adr/0003-local-first-contract-testing.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any


class FakeBedrockRuntimeClient:
    """Stand-in for `boto3.client("bedrock-runtime")`."""

    def __init__(
        self,
        converse_response: dict[str, Any] | None = None,
        converse_error: dict[str, Any] | None = None,
        stream_events: list[dict[str, Any]] | None = None,
        embed_response: dict[str, Any] | None = None,
    ) -> None:
        self._converse_response = converse_response
        self._converse_error = converse_error
        self._stream_events = stream_events or []
        self._embed_response = embed_response

    def _maybe_raise(self) -> None:
        if self._converse_error is not None:
            from botocore.exceptions import ClientError

            raise ClientError(self._converse_error, "Converse")

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_raise()
        assert self._converse_response is not None
        return self._converse_response

    def converse_stream(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_raise()
        return {"stream": iter(self._stream_events)}

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        import io
        import json

        self._maybe_raise()
        assert self._embed_response is not None
        return {"body": io.BytesIO(json.dumps(self._embed_response).encode("utf-8"))}

    def list_foundation_models(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_raise()
        return {"modelSummaries": []}


class _FakeCompletions:
    def __init__(
        self,
        response: Any = None,
        error: Exception | None = None,
        stream_chunks: list[Any] | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self._stream_chunks = stream_chunks or []

    async def create(self, **kwargs: Any) -> Any:
        if self._error is not None:
            raise self._error
        if kwargs.get("stream"):
            return _fake_async_iter(self._stream_chunks)
        return self._response


class _FakeEmbeddings:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def create(self, **kwargs: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._response


class _FakeModels:
    async def list(self) -> dict[str, Any]:
        return {"data": []}


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class FakeAzureOpenAIClient:
    """Stand-in for `openai.AsyncAzureOpenAI`."""

    def __init__(
        self,
        chat_response: Any = None,
        chat_error: Exception | None = None,
        stream_chunks: list[Any] | None = None,
        embedding_response: Any = None,
        embedding_error: Exception | None = None,
    ) -> None:
        self.chat = _FakeChat(_FakeCompletions(chat_response, chat_error, stream_chunks))
        self.embeddings = _FakeEmbeddings(embedding_response, embedding_error)
        self.models = _FakeModels()


async def _fake_async_iter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item
