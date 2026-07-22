"""Read-only SQL query tool.

Defense in depth against a model-issued query doing anything but reading
data (see docs/threat-model.md, "agent tool used to write/exfiltrate via
SQL"):
  1. reject anything but a single statement (no `;`-separated batches),
  2. the statement must start with SELECT/WITH,
  3. reject the whole query if it contains any data-modifying or DDL
     keyword anywhere (catches data-modifying CTEs, not just the leading
     keyword),
  4. wrap the query in an outer `SELECT ... LIMIT` so no query can return
     more than `max_rows`, and
  5. in production this tool should additionally run under a database role
     that only has SELECT grants — this code is the application-level
     control, not a substitute for that database-level one.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.agent.tools.base import Tool, ToolExecutionError

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|"
    r"EXEC|EXECUTE|CALL|MERGE|COPY|VACUUM)\b",
    re.IGNORECASE,
)
_LEADING_SELECT_OR_CTE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


class SqlReadOnlyArgs(BaseModel):
    query: str = Field(..., description="A single read-only SQL SELECT statement")


class SqlReadOnlyTool(Tool[SqlReadOnlyArgs]):
    name = "sql_query_readonly"
    description = (
        "Run a read-only SQL SELECT query and return up to 100 rows. "
        "INSERT/UPDATE/DELETE/DDL statements are rejected."
    )
    args_model = SqlReadOnlyArgs
    timeout_s = 5.0
    max_rows = 100

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _validate(self, query: str) -> str:
        stripped = query.strip().rstrip(";")
        if ";" in stripped:
            raise ToolExecutionError("multiple statements are not allowed")
        if not _LEADING_SELECT_OR_CTE.match(stripped):
            raise ToolExecutionError("only SELECT (or read-only WITH) statements are allowed")
        if _FORBIDDEN_KEYWORDS.search(stripped):
            raise ToolExecutionError("query contains a forbidden keyword")
        return stripped

    async def run(self, arguments: SqlReadOnlyArgs) -> list[dict[str, Any]]:
        query = self._validate(arguments.query)
        wrapped = text(f"SELECT * FROM ({query}) AS aegis_sql_tool_subquery LIMIT :row_limit")
        try:
            result = await self._session.execute(wrapped, {"row_limit": self.max_rows})
        except Exception as exc:  # noqa: BLE001 — surfaced to the model as a tool error
            raise ToolExecutionError(f"query execution failed: {exc}") from exc
        return [dict(row._mapping) for row in result]
