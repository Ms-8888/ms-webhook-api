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
