import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.db.base import Base
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role


@pytest.fixture
async def store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield ApiKeyStore(session)
    await engine.dispose()


async def test_create_and_authenticate(store) -> None:
    key_id, raw_secret = await store.create("t-1", Role.DEVELOPER)

    record = await store.authenticate(key_id, raw_secret)

    assert record is not None
    assert record.tenant_id == "t-1"
    assert record.role == Role.DEVELOPER.value


async def test_authenticate_fails_with_wrong_secret(store) -> None:
    key_id, _raw_secret = await store.create("t-1", Role.DEVELOPER)

    record = await store.authenticate(key_id, "totally-wrong-secret")

    assert record is None


async def test_raw_secret_is_never_recoverable_from_storage(store) -> None:
    key_id, raw_secret = await store.create("t-1", Role.VIEWER)

    record = await store.find_active(key_id)

    assert record is not None
    assert record.hashed_secret != raw_secret
    assert raw_secret not in record.hashed_secret


async def test_revoke_disables_authentication(store) -> None:
    key_id, raw_secret = await store.create("t-1", Role.ADMIN)
    await store.revoke(key_id)

    record = await store.authenticate(key_id, raw_secret)

    assert record is None


async def test_rotate_revokes_old_key_and_issues_a_new_one(store) -> None:
    old_key_id, old_secret = await store.create("t-1", Role.DEVELOPER)

    new_key_id, new_secret = await store.rotate(old_key_id)

    assert new_key_id != old_key_id
    assert await store.authenticate(old_key_id, old_secret) is None
    new_record = await store.authenticate(new_key_id, new_secret)
    assert new_record is not None
    assert new_record.tenant_id == "t-1"
    assert new_record.role == Role.DEVELOPER.value
    assert new_record.rotated_from is not None


async def test_rotate_unknown_key_raises(store) -> None:
    with pytest.raises(ValueError):
        await store.rotate("key_does_not_exist")
