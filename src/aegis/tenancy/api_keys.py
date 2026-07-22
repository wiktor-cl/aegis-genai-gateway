"""API key issuance, verification, and rotation.

The raw secret is returned exactly once, at creation/rotation time, and only
its Argon2 hash is ever persisted (see `aegis.db.models.ApiKey`). Rotating a
key revokes the old row (`revoked_at` set) and inserts a new one with
`rotated_from` pointing back at it, so "which key was live when" is never
lost from the audit trail.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.db.models import ApiKey
from aegis.tenancy.models import Role

_hasher = PasswordHasher()


def _new_key_id() -> str:
    return f"key_{secrets.token_hex(6)}"


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(raw_secret: str) -> str:
    return _hasher.hash(raw_secret)


def verify_secret(raw_secret: str, hashed_secret: str) -> bool:
    try:
        return _hasher.verify(hashed_secret, raw_secret)
    except VerifyMismatchError:
        return False


class ApiKeyStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tenant_id: str, role: Role) -> tuple[str, str]:
        """Returns (key_id, raw_secret). The caller must show `raw_secret`
        to the tenant now — it cannot be recovered later, only rotated."""
        key_id = _new_key_id()
        raw_secret = _new_secret()
        record = ApiKey(
            key_id=key_id,
            tenant_id=tenant_id,
            role=role.value,
            hashed_secret=hash_secret(raw_secret),
        )
        self._session.add(record)
        await self._session.flush()
        return key_id, raw_secret

    async def find_active(self, key_id: str) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.key_id == key_id, ApiKey.revoked_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def revoke(self, key_id: str) -> None:
        record = await self.find_active(key_id)
        if record is not None:
            record.revoked_at = datetime.now(UTC)
            await self._session.flush()

    async def rotate(self, key_id: str) -> tuple[str, str]:
        """Revokes `key_id` and issues a fresh key for the same tenant/role."""
        old = await self.find_active(key_id)
        if old is None:
            raise ValueError(f"no active api key: {key_id}")

        old.revoked_at = datetime.now(UTC)
        new_key_id = _new_key_id()
        raw_secret = _new_secret()
        new_record = ApiKey(
            key_id=new_key_id,
            tenant_id=old.tenant_id,
            role=old.role,
            hashed_secret=hash_secret(raw_secret),
            rotated_from=old.id,
        )
        self._session.add(new_record)
        await self._session.flush()
        return new_key_id, raw_secret

    async def authenticate(self, key_id: str, raw_secret: str) -> ApiKey | None:
        record = await self.find_active(key_id)
        if record is None:
            return None
        if not verify_secret(raw_secret, record.hashed_secret):
            return None
        return record
