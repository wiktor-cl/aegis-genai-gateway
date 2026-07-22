"""Authentication (API key -> Principal) and RBAC enforcement.

`require_role` is a FastAPI dependency factory used on routes; the more
important enforcement point is that `Principal.tenant_id` — never a
client-supplied tenant_id in the request body — is what gets passed down
into the DB-query layer (see `TraceStore.get_run`/`replay`, which filter by
tenant_id at the query itself). That is what "enforced at the query level,
not the presentation layer" means concretely in this codebase: a developer
role's query is scoped in the SQL, not merely hidden in the UI.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.db.session import get_session
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import ROLE_RANK, Role


@dataclass
class Principal:
    tenant_id: str
    role: Role
    key_id: str


async def get_current_principal(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ")
    try:
        key_id, raw_secret = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="malformed API key") from None

    record = await ApiKeyStore(session).authenticate(key_id, raw_secret)
    if record is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")

    return Principal(tenant_id=record.tenant_id, role=Role(record.role), key_id=record.key_id)


def require_role(minimum: Role) -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def _check(principal: Principal = Depends(get_current_principal)) -> Principal:
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail=f"requires role >= {minimum.value}")
        return principal

    return _check
