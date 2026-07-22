"""Provider-agnostic contract every LLM backend implements.

See docs/adr/0001-provider-abstraction-layer.md for the rationale: application
code (agent runtime, API routes) only ever depends on `LLMProvider` and the
request/response models below — never on a provider SDK's native types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(BaseModel):
    """JSON-schema description of a callable tool, provider-agnostic."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str
    tools: list[ToolSpec] = Field(default_factory=list)
    temperature: float = 0.2
    max_output_tokens: int = 1024
    tenant_id: str
    request_id: str


class ChatResponse(BaseModel):
    message: ChatMessage
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage
    provider_name: str
    model: str
    finish_reason: str = "stop"
    raw: dict[str, Any] = Field(default_factory=dict)
    """Provider-specific detail. Never read by core logic, only surfaced for debugging/audit."""


class StreamChunk(BaseModel):
    delta: str
    finish_reason: str | None = None
    usage: Usage | None = None


class EmbedRequest(BaseModel):
    inputs: list[str]
    model: str
    tenant_id: str
    request_id: str


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    usage: Usage
    provider_name: str
    model: str


class ProviderError(Exception):
    """Base class for all provider failures. Routers/circuit breakers key off this."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    """Raised for connection failures, 5xx, throttling — anything retryable/failover-able."""


class ProviderAuthError(ProviderError):
    """Raised for 401/403 — not retryable, not failover-able, surfaced to caller immediately."""


class LLMProvider(ABC):
    """Contract implemented by LocalProvider, BedrockProvider, FoundryProvider.

    Implementations must not perform data-classification or cost-policy logic —
    that is the router's job (ADR-0002). A provider's only responsibility is
    "given this provider-agnostic request, talk to my backend and return a
    provider-agnostic response, or raise a ProviderError subtype".
    """

    name: str

    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    # Implementations are `async def ...: yield ...` (an async-generator
    # function, not a coroutine) — hence no `async` on this abstract signature.
    @abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    async def embed(self, request: EmbedRequest) -> EmbedResponse: ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Cheap liveness probe used by the router/circuit breaker, not a chat call."""
        ...
