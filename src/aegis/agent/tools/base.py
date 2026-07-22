"""Tool contract used by the agent runtime's registry.

Every tool declares a Pydantic model for its arguments (`args_model`) — the
runtime validates the model's tool-call arguments against it *before*
`run()` is ever called, so a malformed or hallucinated argument never
reaches tool implementation code (see docs/threat-model.md, "agent calls a
tool with attacker-influenced arguments").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

from aegis.providers.base import ToolSpec


class ToolExecutionError(Exception):
    """Raised by a tool's `run()` for any failure the runtime should surface
    back to the model as a tool result, rather than crashing the run."""


class Tool[TArgs: BaseModel](ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]
    # Not a ClassVar: a couple of tools override this per-instance (e.g. the
    # HTTP tool's caller-configured timeout), so it must stay assignable.
    timeout_s: float = 10.0

    @abstractmethod
    async def run(self, arguments: TArgs) -> Any: ...

    @classmethod
    def spec(cls) -> ToolSpec:
        return ToolSpec(
            name=cls.name,
            description=cls.description,
            parameters=cls.args_model.model_json_schema(),
        )
