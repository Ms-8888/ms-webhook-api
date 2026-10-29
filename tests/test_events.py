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


@pytest.mark.asyncio
async def test_oversized_payload_returns_413(client, tenant, monkeypatch):
    monkeypatch.setattr("app.routers.events.settings.max_event_payload_bytes", 100)
    _, api_key = tenant
    response = await client.post(
        "/events",
        json={"event_type": "big", "payload": {"blob": "x" * 200}},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 413
    assert "maximum is 100 bytes" in response.json()["detail"]


@pytest.mark.asyncio
async def test_payload_at_the_limit_is_accepted(client, tenant, monkeypatch):
    import json

    payload = {"blob": "x" * 50}
    monkeypatch.setattr(
        "app.routers.events.settings.max_event_payload_bytes", len(json.dumps(payload).encode())
    )
    _, api_key = tenant
    response = await client.post(
        "/events", json={"event_type": "ok", "payload": payload}, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 202
