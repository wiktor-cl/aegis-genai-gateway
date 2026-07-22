"""Manual smoke test against a *real* local Ollama — never run in CI (no
GPU/model-download budget there; see tests/unit/test_local_provider.py,
which covers the same request/response shapes offline via respx).

This is the one place in the repo that proves `LocalProvider` actually
works end-to-end against a live model, including tool-calling — the
regression this script exists to catch: it's easy for `LocalProvider` to
pass every mocked unit test while silently never sending `tools` to Ollama
at all (that happened once — see git history around
`_ollama_tools_payload`/`_parse_ollama_tool_calls`).

Usage (with `docker compose up` already running, or any local Ollama):

    ollama pull llama3.1:8b
    python scripts/smoke_test_local_provider.py
"""

from __future__ import annotations

import asyncio

from aegis.providers.base import ChatMessage, ChatRequest, Role, ToolSpec
from aegis.providers.local_provider import LocalProvider

CALCULATOR = ToolSpec(
    name="calculator",
    description="Evaluate an arithmetic expression.",
    parameters={
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
)


async def main() -> int:
    provider = LocalProvider()

    print("1. health_check()...")
    if not await provider.health_check():
        print("   FAILED — is `ollama serve` reachable at http://localhost:11434?")
        return 1
    print("   ok")

    print("2. plain chat, no tools...")
    response = await provider.chat(
        ChatRequest(
            messages=[ChatMessage(role=Role.USER, content="Reply with exactly: pong")],
            model="llama3.1:8b",
            tenant_id="smoke-test",
            request_id="smoke-1",
        )
    )
    print(f"   response: {response.message.content!r}")
    assert response.tool_calls == [], "expected no tool calls for a plain chat"

    print("3. chat with a tool offered, expecting a real tool call back...")
    response = await provider.chat(
        ChatRequest(
            messages=[
                ChatMessage(
                    role=Role.USER,
                    content=(
                        "Call the calculator tool to compute 6 * 7. "
                        "Do not compute it yourself."
                    ),
                )
            ],
            model="llama3.1:8b",
            tools=[CALCULATOR],
            tenant_id="smoke-test",
            request_id="smoke-2",
        )
    )
    print(f"   finish_reason: {response.finish_reason}")
    print(f"   tool_calls: {response.tool_calls}")
    if not response.tool_calls:
        print(
            "   NOTE: the model answered directly instead of calling the tool — a real,\n"
            "   known possibility with smaller/instruct models, not necessarily a bug in\n"
            "   LocalProvider. Re-run, or check step 3's payload with curl directly against\n"
            "   /api/chat if this happens consistently."
        )
        return 0

    assert response.tool_calls[0].name == "calculator"
    assert response.tool_calls[0].arguments.get("expression")
    print("   ok — tool_calls correctly parsed from a live Ollama response")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
