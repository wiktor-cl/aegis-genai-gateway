from aegis.tenancy.api_keys import ApiKeyStore
from aegis.tenancy.models import Role
from tests.unit.conftest import auth_header


async def _mint(session_factory, tenant_id: str, role: Role) -> str:
    async with session_factory() as session:
        key_id, secret = await ApiKeyStore(session).create(tenant_id, role)
        await session.commit()
    return f"{key_id}.{secret}"


async def test_admin_can_create_api_key(app_client) -> None:
    client, session_factory = app_client
    admin_token = await _mint(session_factory, "acme-support", Role.ADMIN)

    resp = client.post(
        "/v1/admin/api-keys",
        json={"tenant_id": "acme-legal", "role": "developer"},
        headers=auth_header(admin_token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_id"] == "acme-legal"
    assert body["role"] == "developer"
    assert body["raw_secret"]


async def test_developer_cannot_create_api_key(app_client) -> None:
    client, session_factory = app_client
    dev_token = await _mint(session_factory, "acme-support", Role.DEVELOPER)

    resp = client.post(
        "/v1/admin/api-keys",
        json={"tenant_id": "acme-legal", "role": "viewer"},
        headers=auth_header(dev_token),
    )

    assert resp.status_code == 403


async def test_admin_can_rotate_a_key_and_old_one_stops_working(app_client) -> None:
    client, session_factory = app_client
    admin_token = await _mint(session_factory, "acme-support", Role.ADMIN)

    created = client.post(
        "/v1/admin/api-keys",
        json={"tenant_id": "acme-support", "role": "developer"},
        headers=auth_header(admin_token),
    ).json()
    old_key_id = created["key_id"]
    old_token = f"{old_key_id}.{created['raw_secret']}"

    rotated = client.post(
        f"/v1/admin/api-keys/{old_key_id}/rotate", headers=auth_header(admin_token)
    )
    assert rotated.status_code == 200
    new_token = f"{rotated.json()['key_id']}.{rotated.json()['raw_secret']}"

    # Old key must no longer authenticate anything.
    resp_old = client.post(
        "/v1/agents/run", json={"user_message": "hi"}, headers=auth_header(old_token)
    )
    assert resp_old.status_code == 401

    # New key works for a run trigger (developer role).
    resp_new = client.post(
        "/v1/agents/run",
        json={"user_message": "hi", "data_classification": "confidential"},
        headers=auth_header(new_token),
    )
    assert resp_new.status_code == 200


async def test_admin_can_revoke_a_key(app_client) -> None:
    client, session_factory = app_client
    admin_token = await _mint(session_factory, "acme-support", Role.ADMIN)

    created = client.post(
        "/v1/admin/api-keys",
        json={"tenant_id": "acme-support", "role": "viewer"},
        headers=auth_header(admin_token),
    ).json()
    token = f"{created['key_id']}.{created['raw_secret']}"

    revoke_resp = client.post(
        f"/v1/admin/api-keys/{created['key_id']}/revoke", headers=auth_header(admin_token)
    )
    assert revoke_resp.status_code == 204

    resp = client.get("/v1/cost/report", headers=auth_header(token))
    assert resp.status_code == 401
