"""Deterministic fake `LLMProvider` for the CI eval-gate.

See docs/adr/0008-eval-gate-golden-fixtures.md: this plays back an
`EvalCase`'s `golden_tool_calls`/`golden_final_text` as a scripted
conversation — one `ChatResponse` per tool call, then a final text
response — the same pattern as `ScriptedProvider` in
`tests/unit/test_runtime.py`, but driven by fixture data instead of being
hand-written per test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from aegis.eval.models import EvalCase
from aegis.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbedRequest,
    EmbedResponse,
    LLMProvider,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)


class GoldenScriptProvider(LLMProvider):
    """Scripted provider driven by one `EvalCase`'s golden fixtures.

    Exhausting the script (more LLM calls happen than golden steps
    describe) raises `AssertionError` rather than silently looping —
    a case whose runtime behavior diverges from its fixture should fail
    loudly, not hang or fall back to a default response.
    """

    name = "golden"

    def __init__(self, case: EvalCase) -> None:
        self._case = case
        self._pending: list[ChatResponse] = list(_script(case))
        self.call_count = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.call_count += 1
        if not self._pending:
            raise AssertionError(
                f"eval case {self._case.id!r}: provider called more times than the "
                "golden fixture script has steps for"
            )
        return self._pending.pop(0)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        response = await self.chat(request)
        yield StreamChunk(delta=response.message.content, finish_reason=response.finish_reason)

    async def embed(self, request: EmbedRequest) -> EmbedResponse:
        raise NotImplementedError("golden provider does not script embeddings")

    async def health_check(self) -> bool:
        return True


def _script(case: EvalCase) -> list[ChatResponse]:
    steps: list[ChatResponse] = []
    for i, golden_call in enumerate(case.golden_tool_calls):
        steps.append(
            ChatResponse(
                message=ChatMessage(role=Role.ASSISTANT, content=""),
                tool_calls=[
                    ToolCall(
                        id=f"golden-{i}",
                        name=golden_call.tool,
                        arguments=golden_call.arguments,
                    )
                ],
                usage=Usage(input_tokens=20, output_tokens=8),
                provider_name="golden",
                model="golden-fixture",
                finish_reason="tool_use",
            )
        )
    steps.append(
        ChatResponse(
            message=ChatMessage(role=Role.ASSISTANT, content=case.golden_final_text),
            usage=Usage(input_tokens=10, output_tokens=5),
            provider_name="golden",
            model="golden-fixture",
        )
    )
    return steps
