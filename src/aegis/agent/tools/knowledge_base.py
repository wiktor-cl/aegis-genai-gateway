"""Knowledge-base search tool.

Keyword-overlap scoring over a small local JSON corpus — deterministic and
network-free, so it is trivially unit-testable without any provider running.
`LLMProvider.embed()` already exists (see docs/adr/0001) — swapping this for
semantic/embedding-based search over the same corpus is a natural follow-up,
not implemented here to keep the tool free of any provider dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from aegis.agent.tools.base import Tool

_DEFAULT_DOCS_PATH = Path(__file__).parent / "knowledge_base_docs.json"


class KnowledgeBaseSearchArgs(BaseModel):
    query: str = Field(..., description="Natural-language search query")
    top_k: int = Field(3, ge=1, le=10)


class KnowledgeBaseSearchTool(Tool[KnowledgeBaseSearchArgs]):
    name = "knowledge_base_search"
    description = "Search the internal knowledge base for documents relevant to a query."
    args_model = KnowledgeBaseSearchArgs
    timeout_s = 3.0

    def __init__(self, docs_path: Path | None = None) -> None:
        path = docs_path or _DEFAULT_DOCS_PATH
        self._docs: list[dict] = json.loads(path.read_text(encoding="utf-8"))

    async def run(self, arguments: KnowledgeBaseSearchArgs) -> list[dict]:
        terms = {t.lower() for t in arguments.query.split() if len(t) > 2}
        scored: list[tuple[int, dict]] = []
        for doc in self._docs:
            haystack = f"{doc['title']} {doc['body']}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"id": doc["id"], "title": doc["title"], "snippet": doc["body"][:280], "score": score}
            for score, doc in scored[: arguments.top_k]
        ]
