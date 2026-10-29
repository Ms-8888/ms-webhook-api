import pytest


@pytest.mark.asyncio
async def test_create_endpoint(client, tenant):
    _, api_key = tenant
    response = await client.post(
        "/endpoints",
        json={"url": "https://example.com/webhook", "description": "Test endpoint"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["url"] == "https://example.com/webhook"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_endpoints(client, tenant):
    _, api_key = tenant
    response = await client.get("/endpoints", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_delete_endpoint(client, tenant):
    _, api_key = tenant
    create = await client.post(
        "/endpoints",
        json={"url": "https://example.com/delete-me"},
        headers={"X-API-Key": api_key},
    )
    endpoint_id = create.json()["id"]

    delete = await client.delete(f"/endpoints/{endpoint_id}", headers={"X-API-Key": api_key})
    assert delete.status_code == 204

    list_resp = await client.get("/endpoints", headers={"X-API-Key": api_key})
    ids = [e["id"] for e in list_resp.json()]
    assert endpoint_id not in ids


@pytest.mark.asyncio
async def test_reject_localhost_url(client, tenant):
    _, api_key = tenant
    response = await client.post(
        "/endpoints",
        json={"url": "http://localhost:8080/hook"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_private_ip_url(client, tenant):
    _, api_key = tenant
    response = await client.post(
        "/endpoints",
        json={"url": "http://192.168.1.1/hook"},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_api_key(client):
    response = await client.get("/endpoints", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


async def _add(client, key, path):
    return await client.post(
        "/endpoints", json={"url": f"https://example.com/{path}"}, headers={"X-API-Key": key}
    )


@pytest.mark.asyncio
async def test_active_endpoint_cap_returns_409(client, tenant, monkeypatch):
    monkeypatch.setattr("app.routers.endpoints.settings.max_active_endpoints_per_tenant", 2)
    _, api_key = tenant
    for i in range(2):
        assert (await _add(client, api_key, str(i))).status_code == 201

    over = await _add(client, api_key, "over")
    assert over.status_code == 409
    assert "limit" in over.json()["detail"].lower()
    assert "2" in over.json()["detail"]


@pytest.mark.asyncio
async def test_deleted_endpoint_frees_a_slot(client, tenant, monkeypatch):
    monkeypatch.setattr("app.routers.endpoints.settings.max_active_endpoints_per_tenant", 1)
    _, api_key = tenant
    first = await _add(client, api_key, "a")
    assert first.status_code == 201
    assert (await _add(client, api_key, "b")).status_code == 409

    await client.delete(f"/endpoints/{first.json()['id']}", headers={"X-API-Key": api_key})
    assert (await _add(client, api_key, "b")).status_code == 201


@pytest.mark.asyncio
async def test_endpoint_cap_is_per_tenant(client, db, tenant, monkeypatch):
    import secrets

    from app.models import Tenant

    monkeypatch.setattr("app.routers.endpoints.settings.max_active_endpoints_per_tenant", 1)
    _, key_a = tenant
    other_key = secrets.token_hex(16)
    db.add(Tenant(name="Other", api_key_hash=Tenant.hash_api_key(other_key)))
    await db.commit()

    assert (await _add(client, key_a, "a")).status_code == 201
    assert (await _add(client, other_key, "a")).status_code == 201
