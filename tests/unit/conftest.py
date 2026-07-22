"""Shared fixture for API-level tests: a real FastAPI app wired to an
in-memory SQLite DB (via dependency override), so no external Postgres is
needed to exercise the HTTP layer end to end, including real RBAC/API-key
authentication against that same in-memory DB.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from aegis.db.base import Base
from aegis.db.session import get_session
from aegis.main import create_app


@pytest.fixture
async def app_client():
    app = create_app()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session

    with TestClient(app) as client:
        yield client, session_factory
    await engine.dispose()


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
