"""Integration test: SqlReadOnlyTool against a real, ephemeral Postgres.

Requires a running Docker daemon (Testcontainers spins up and tears down a
throwaway `postgres:16-alpine` container for the duration of this module).
Skipped automatically — not failed — if Docker isn't available, so `pytest`
still runs clean in an environment without Docker (see docs/adr/0003, which
covers the equivalent offline-first principle for provider contract tests).
This is deliberately separate from `pytest tests/unit tests/contract`, the
fast/offline default: run it explicitly with `pytest tests/integration`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.agent.tools.sql_readonly import SqlReadOnlyArgs, SqlReadOnlyTool

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def postgres_container():
    if not _docker_available():
        pytest.skip("Docker is not available in this environment")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as container:
        yield container


async def test_readonly_tool_against_real_postgres(postgres_container) -> None:
    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)"))
        await conn.execute(
            text("INSERT INTO widgets (id, name) VALUES (1, 'left'), (2, 'right')")
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        tool = SqlReadOnlyTool(session)
        rows = await tool.run(SqlReadOnlyArgs(query="SELECT * FROM widgets ORDER BY id"))

    assert rows == [{"id": 1, "name": "left"}, {"id": 2, "name": "right"}]
    await engine.dispose()


async def test_readonly_tool_rejects_write_against_real_postgres(postgres_container) -> None:
    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    engine = create_async_engine(url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from aegis.agent.tools.base import ToolExecutionError

    async with session_factory() as session:
        tool = SqlReadOnlyTool(session)
        with pytest.raises(ToolExecutionError):
            await tool.run(SqlReadOnlyArgs(query="DELETE FROM widgets"))

    await engine.dispose()
