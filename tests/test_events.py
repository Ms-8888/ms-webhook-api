import pytest


@pytest.mark.asyncio
async def test_fire_event(client, tenant):
    _, api_key = tenant
    response = await client.post(
        "/events",
        json={"event_type": "order.created", "payload": {"order_id": 42}},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 202
    data = response.json()
    assert "event_id" in data
    assert "queued_deliveries" in data


@pytest.mark.asyncio
async def test_list_events(client, tenant):
    _, api_key = tenant
    response = await client.get("/events", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_deliveries(client, tenant):
    _, api_key = tenant
    fire = await client.post(
        "/events",
        json={"event_type": "user.signup", "payload": {"user_id": 1}},
        headers={"X-API-Key": api_key},
    )
    event_id = fire.json()["event_id"]

    response = await client.get(f"/events/{event_id}/deliveries", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in ("ok", "degraded")
