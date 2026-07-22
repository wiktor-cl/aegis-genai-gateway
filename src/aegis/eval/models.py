"""Eval case schema.

Two execution modes:
  - `chat`: a single request/response through `LLMProvider.chat()` directly
    — no tools, evaluated on the raw response text.
  - `agent`: runs through the full `AgentRuntime` (tools + guardrails), for
    cases that require tool use or exercise guardrail behavior.

`golden_tool_calls`/`golden_final_text` are only used by the CI eval-gate's
deterministic fake provider (see docs/adr/0008-eval-gate-golden-fixtures.md)
— they describe what a "known good" model would do for this case, so the
gate can exercise real tool execution and real guardrail behavior without
depending on a live, non-deterministic model call.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Assertion(BaseModel):
    type: str
    """contains | not_contains | regex | tool_called | status_equals |
    input_contains | input_not_contains

    The `input_*` variants check the guardrail-screened request text (what
    would actually be sent to the provider) rather than the response —
    used to verify PII redaction independent of the scripted model reply.
    """
    value: str


class GoldenToolCall(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


class EvalCase(BaseModel):
    id: str
    category: str
    mode: str = "chat"
    """chat | agent"""
    system_prompt: str = "You are a helpful, factual assistant. Answer concisely."
    user_message: str
    assertions: list[Assertion]
    tags: list[str] = Field(default_factory=list)

    golden_tool_calls: list[GoldenToolCall] = Field(default_factory=list)
    golden_final_text: str = ""

    guardrail_policy: str | None = None
    """Tenant guardrail policy name to screen this case's request/response
    through (see policies/guardrails.yaml). None uses the default policy."""


def load_cases(directory: Path | str) -> list[EvalCase]:
    directory = Path(directory)
    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in raw["cases"]:
            cases.append(EvalCase(**item))
    return cases
