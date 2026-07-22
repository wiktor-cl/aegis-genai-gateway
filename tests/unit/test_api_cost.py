from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role
from tests.unit.conftest import auth_header


async def _mint(session_factory, tenant_id: str, role: Role) -> str:
    async with session_factory() as session:
        key_id, secret = await ApiKeyStore(session).create(tenant_id, role)
        await session.commit()
    return f"{key_id}.{secret}"


async def test_developer_sees_own_tenant_cost_report(app_client) -> None:
    client, session_factory = app_client
    token = await _mint(session_factory, "acme-support", Role.DEVELOPER)

    resp = client.get("/v1/cost/report", headers=auth_header(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "acme-support"
    assert body["monthly_budget_usd"] == 500.0
    assert body["status"] == "ok"


async def test_developer_cannot_view_another_tenants_report(app_client) -> None:
    client, session_factory = app_client
    token = await _mint(session_factory, "acme-support", Role.DEVELOPER)

    resp = client.get(
        "/v1/cost/report", params={"tenant_id": "acme-legal"}, headers=auth_header(token)
    )

    assert resp.status_code == 403


async def test_admin_can_view_any_tenants_report(app_client) -> None:
    client, session_factory = app_client
    admin_token = await _mint(session_factory, "acme-support", Role.ADMIN)

    resp = client.get(
        "/v1/cost/report", params={"tenant_id": "acme-legal"}, headers=auth_header(admin_token)
    )

    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == "acme-legal"


async def test_unknown_tenant_returns_404(app_client) -> None:
    client, session_factory = app_client
    admin_token = await _mint(session_factory, "acme-support", Role.ADMIN)

    resp = client.get(
        "/v1/cost/report", params={"tenant_id": "does-not-exist"}, headers=auth_header(admin_token)
    )

    assert resp.status_code == 404
