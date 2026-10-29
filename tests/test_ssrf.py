from datetime import datetime, timedelta, timezone

import pytest

from app.database import AsyncSessionLocal
from app.models import Delivery, Endpoint, Event
from app.services import auth
from app.services.dispatcher import QUEUE_KEY
from app.services.worker import _pin_request, requeue_due_deliveries


def _resolves_to(monkeypatch, *addresses):
    async def fake(host, port):
        return [(2, 1, 6, "", (a, port)) for a in addresses]

    monkeypatch.setattr("app.services.auth._getaddrinfo", fake)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://0.0.0.0/x",
        "http://10.1.2.3/x",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.0.1/x",
        "http://[::1]/x",
        "http://[fc00::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://localhost/x",
        "ftp://example.com/x",
    ],
)
async def test_unsafe_literal_urls_are_rejected(url):
    assert await auth.validate_endpoint_url(url) is not None


@pytest.mark.asyncio
async def test_public_hostname_is_accepted():
    assert await auth.validate_endpoint_url("https://hooks.example.com/in") is None


@pytest.mark.asyncio
async def test_hostname_resolving_to_private_address_is_rejected(monkeypatch):
    _resolves_to(monkeypatch, "10.0.0.5")
    assert await auth.validate_endpoint_url("https://innocent.example.com/in") == auth.BLOCKED_MESSAGE


@pytest.mark.asyncio
async def test_one_private_address_among_public_ones_rejects_the_url(monkeypatch):
    _resolves_to(monkeypatch, "93.184.216.34", "192.168.0.10")
    assert await auth.validate_endpoint_url("https://mixed.example.com/in") == auth.BLOCKED_MESSAGE


@pytest.mark.asyncio
async def test_unresolvable_hostname_is_rejected(monkeypatch):
    async def boom(host, port):
        raise OSError("no such host")

    monkeypatch.setattr("app.services.auth._getaddrinfo", boom)
    assert await auth.validate_endpoint_url("https://nope.example.com/in") == "URL hostname could not be resolved"


@pytest.mark.asyncio
async def test_api_rejects_hostname_that_resolves_to_private_address(client, tenant, monkeypatch):
    _, api_key = tenant
    _resolves_to(monkeypatch, "127.0.0.1")
    response = await client.post(
        "/endpoints", json={"url": "https://rebind.example.com/hook"}, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 422


def test_pinned_request_keeps_name_for_host_header_and_tls():
    url, headers, extensions = _pin_request("https://hooks.example.com:8443/in?x=1", "93.184.216.34")
    assert url.host == "93.184.216.34" and url.port == 8443 and url.path == "/in"
    assert headers == {"Host": "hooks.example.com:8443"}
    assert extensions == {"sni_hostname": "hooks.example.com"}


@pytest.mark.asyncio
async def test_retry_worker_requeues_delivery_that_never_reached_the_queue(tenant, redis_client):
    t, _ = tenant
    async with AsyncSessionLocal() as db:
        endpoint = Endpoint(tenant_id=t.id, url="https://hooks.example.com/in")
        event = Event(tenant_id=t.id, event_type="order.created", payload={"id": 1})
        db.add_all([endpoint, event])
        await db.flush()
        old = Delivery(
            event_id=event.id,
            endpoint_id=endpoint.id,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        fresh = Delivery(event_id=event.id, endpoint_id=endpoint.id)
        db.add_all([old, fresh])
        await db.commit()
        old_id = old.id

    assert await requeue_due_deliveries(redis_client) == 1
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == [str(old_id)]
