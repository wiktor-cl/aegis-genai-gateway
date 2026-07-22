import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.agent.tools.base import ToolExecutionError
from aegis.agent.tools.sql_readonly import SqlReadOnlyArgs, SqlReadOnlyTool


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)"))
        await conn.execute(text("INSERT INTO widgets (id, name) VALUES (1, 'left'), (2, 'right')"))

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s
    await engine.dispose()


async def test_select_returns_rows(session) -> None:
    tool = SqlReadOnlyTool(session)
    rows = await tool.run(SqlReadOnlyArgs(query="SELECT * FROM widgets ORDER BY id"))
    assert rows == [{"id": 1, "name": "left"}, {"id": 2, "name": "right"}]


async def test_rejects_insert(session) -> None:
    tool = SqlReadOnlyTool(session)
    with pytest.raises(ToolExecutionError):
        await tool.run(SqlReadOnlyArgs(query="INSERT INTO widgets (id, name) VALUES (3, 'evil')"))


async def test_rejects_drop_table(session) -> None:
    tool = SqlReadOnlyTool(session)
    with pytest.raises(ToolExecutionError):
        await tool.run(SqlReadOnlyArgs(query="DROP TABLE widgets"))


async def test_rejects_multiple_statements(session) -> None:
    tool = SqlReadOnlyTool(session)
    with pytest.raises(ToolExecutionError):
        await tool.run(SqlReadOnlyArgs(query="SELECT * FROM widgets; DROP TABLE widgets"))


async def test_rejects_data_modifying_cte(session) -> None:
    tool = SqlReadOnlyTool(session)
    query = (
        "WITH deleted AS (DELETE FROM widgets WHERE id = 1 RETURNING *) "
        "SELECT * FROM deleted"
    )
    with pytest.raises(ToolExecutionError):
        await tool.run(SqlReadOnlyArgs(query=query))


async def test_enforces_row_limit(session) -> None:
    tool = SqlReadOnlyTool(session)
    tool.max_rows = 1
    rows = await tool.run(SqlReadOnlyArgs(query="SELECT * FROM widgets ORDER BY id"))
    assert len(rows) == 1
