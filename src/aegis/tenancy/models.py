"""Static tenant registry loaded from policies/tenants.yaml. See
aegis.tenancy.api_keys for the runtime-mutable, DB-backed API key store.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel


class Role(StrEnum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"


# Higher number = more privilege. Used by aegis.tenancy.rbac.require_role.
ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.DEVELOPER: 1, Role.ADMIN: 2}


class Tenant(BaseModel):
    id: str
    display_name: str
    guardrail_policy: str = "standard"
    monthly_budget_usd: float


class TenantRegistry(BaseModel):
    version: int
    tenants: list[Tenant]

    @classmethod
    def from_yaml(cls, path: Path | str) -> TenantRegistry:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(version=raw["version"], tenants=raw["tenants"])

    def get(self, tenant_id: str) -> Tenant | None:
        return next((t for t in self.tenants if t.id == tenant_id), None)
