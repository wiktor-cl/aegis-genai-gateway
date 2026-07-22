"""Bootstrap the first admin API key.

Every other API key is created through `POST /v1/admin/api-keys`, which
itself requires an admin key — a chicken-and-egg problem for a brand new
database. This script is the one place that mints a key by talking to
`ApiKeyStore` directly instead of through the API, which is fine here: it's
an explicit, operator-run, one-time bootstrap step against a database the
operator already has direct access to, not a runtime code path.

Usage (from the repo root, against the docker-compose Postgres):

    AEGIS_DATABASE_URL=postgresql+asyncpg://aegis:aegis@localhost:5432/aegis \\
        python scripts/seed.py --tenant-id acme-support --role admin
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegis.config import settings
from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role


async def _seed(tenant_id: str, role: Role) -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        key_id, raw_secret = await ApiKeyStore(session).create(tenant_id, role)
        await session.commit()
    await engine.dispose()

    print(f"tenant:  {tenant_id}")
    print(f"role:    {role.value}")
    print(f"key_id:  {key_id}")
    print(f"token (Authorization: Bearer <this>, shown once):\n{key_id}.{raw_secret}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default="acme-support", help="must exist in policies/tenants.yaml")
    parser.add_argument("--role", choices=[r.value for r in Role], default="admin")
    args = parser.parse_args()
    asyncio.run(_seed(args.tenant_id, Role(args.role)))


if __name__ == "__main__":
    main()
