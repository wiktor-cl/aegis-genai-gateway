import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.db.base import Base
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role
from aegis.tenancy.rbac import get_current_principal, require_role


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s
    await engine.dispose()


async def test_valid_bearer_token_resolves_to_principal(session) -> None:
    key_id, raw_secret = await ApiKeyStore(session).create("t-1", Role.DEVELOPER)

    principal = await get_current_principal(
        authorization=f"Bearer {key_id}.{raw_secret}", session=session
    )

    assert principal.tenant_id == "t-1"
    assert principal.role == Role.DEVELOPER


async def test_missing_bearer_prefix_is_rejected(session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(authorization="not-a-bearer-token", session=session)
    assert exc_info.value.status_code == 401


async def test_malformed_token_without_dot_is_rejected(session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(authorization="Bearer nodothere", session=session)
    assert exc_info.value.status_code == 401


async def test_unknown_key_id_is_rejected(session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_principal(authorization="Bearer key_bogus.somesecret", session=session)
    assert exc_info.value.status_code == 401


async def test_require_role_allows_sufficient_role(session) -> None:
    key_id, raw_secret = await ApiKeyStore(session).create("t-1", Role.ADMIN)
    principal = await get_current_principal(
        authorization=f"Bearer {key_id}.{raw_secret}", session=session
    )

    checked = await require_role(Role.DEVELOPER)(principal=principal)

    assert checked.role == Role.ADMIN


async def test_require_role_rejects_insufficient_role(session) -> None:
    key_id, raw_secret = await ApiKeyStore(session).create("t-1", Role.VIEWER)
    principal = await get_current_principal(
        authorization=f"Bearer {key_id}.{raw_secret}", session=session
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_role(Role.ADMIN)(principal=principal)
    assert exc_info.value.status_code == 403
