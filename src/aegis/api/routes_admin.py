"""Admin-only API key management: create, rotate, revoke.

Every endpoint here requires `Role.ADMIN` (see aegis.tenancy.rbac) — this is
deliberately the one place in the API where a caller can mint credentials
for another tenant, so it is the most tightly gated route in the system.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.db.session import get_session
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role
from aegis.tenancy.rbac import Principal, require_role

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class CreateApiKeyIn(BaseModel):
    tenant_id: str
    role: Role


class ApiKeyOut(BaseModel):
    key_id: str
    raw_secret: str
    """Shown exactly once — only its hash is ever persisted. Store it now."""
    tenant_id: str
    role: Role


@router.post("/api-keys", response_model=ApiKeyOut)
async def create_api_key(
    body: CreateApiKeyIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyOut:
    key_id, raw_secret = await ApiKeyStore(session).create(body.tenant_id, body.role)
    await session.commit()
    return ApiKeyOut(
        key_id=key_id, raw_secret=raw_secret, tenant_id=body.tenant_id, role=body.role
    )


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyOut)
async def rotate_api_key(
    key_id: str,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyOut:
    store = ApiKeyStore(session)
    try:
        new_key_id, raw_secret = await store.rotate(key_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()

    record = await store.find_active(new_key_id)
    assert record is not None
    return ApiKeyOut(
        key_id=new_key_id, raw_secret=raw_secret, tenant_id=record.tenant_id, role=Role(record.role)
    )


@router.post("/api-keys/{key_id}/revoke", status_code=204)
async def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> None:
    await ApiKeyStore(session).revoke(key_id)
    await session.commit()
