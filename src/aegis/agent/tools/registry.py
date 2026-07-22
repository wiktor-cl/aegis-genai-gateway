from __future__ import annotations

from typing import Any

from aegis.agent.tools.base import Tool
from aegis.providers.base import ToolSpec


class ToolRegistry:
    def __init__(self, tools: list[Tool[Any]]) -> None:
        self._tools: dict[str, Tool[Any]] = {t.name: t for t in tools}

    def get(self, name: str) -> Tool[Any] | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
