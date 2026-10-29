import secrets
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Delivery, Endpoint, Event, Tenant
from app.services import worker
from app.services.auth import validate_endpoint_url
from app.services.worker import MAX_ATTEMPTS, _dispatch_delivery

PUBLIC_IP = "93.184.216.34"
PUBLIC_IPV6 = "2606:4700:4700::1111"


@pytest.fixture(autouse=True)
def _schema(db_engine):
    return db_engine


def _resolver(address):
    async def resolve(host, port):
        return [(2, 1, 6, "", (address, port))]

    return resolve


async def _make_delivery(url: str) -> int:
    async with AsyncSessionLocal() as db:
        key_hash = Tenant.hash_api_key(secrets.token_hex(8))
        tenant = Tenant(name="Delivery Test", api_key_hash=key_hash)
        db.add(tenant)
        await db.flush()
        endpoint = Endpoint(tenant_id=tenant.id, url=url)
        event = Event(tenant_id=tenant.id, event_type="order.created", payload={"order_id": 7})
        db.add_all([endpoint, event])
        await db.flush()
        delivery = Delivery(event_id=event.id, endpoint_id=endpoint.id)
        db.add(delivery)
        await db.commit()
        return delivery.id


async def _load(delivery_id: int) -> Delivery:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Delivery).where(Delivery.id == delivery_id))
        return result.scalar_one()


def _capture_client(monkeypatch, status_code=200):
    """Replace httpx.AsyncClient with one backed by a mock transport; return captured requests."""
    seen: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code)

    def factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(worker.httpx, "AsyncClient", factory)
    return seen


def _forbid_client(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("outbound HTTP must not be attempted")

    monkeypatch.setattr(worker.httpx, "AsyncClient", fail)


async def test_dns_rebinding_to_loopback_is_blocked_before_any_request(
    monkeypatch, redis_client
):
    url = "https://hooks.example.com/in"
    assert await validate_endpoint_url(url) is None
    delivery_id = await _make_delivery(url)

    monkeypatch.setattr("app.services.auth._getaddrinfo", _resolver("127.0.0.1"))
    _forbid_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    delivery = await _load(delivery_id)
    assert delivery.status == "failed"
    assert "blocked" in delivery.last_error.lower()
    assert delivery.delivered_at is None


async def test_public_dns_pins_connection_to_checked_ip(monkeypatch, redis_client):
    delivery_id = await _make_delivery("https://hooks.example.com:8443/in?x=1")
    seen = _capture_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == PUBLIC_IP
    assert request.url.port == 8443
    assert request.url.scheme == "https"
    assert request.url.path == "/in"
    assert request.url.query == b"x=1"
    assert request.headers["Host"] == "hooks.example.com:8443"
    assert request.extensions["sni_hostname"] == "hooks.example.com"
    assert request.headers["X-Event-Type"] == "order.created"
    assert request.headers["X-Webhook-Signature"].startswith("sha256=")

    delivery = await _load(delivery_id)
    assert delivery.status == "delivered"
    assert delivery.attempt_count == 1


async def test_default_port_is_omitted_from_host_header(monkeypatch, redis_client):
    delivery_id = await _make_delivery("https://hooks.example.com/in")
    seen = _capture_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    assert seen[0].headers["Host"] == "hooks.example.com"
    assert seen[0].url.port is None


async def test_ipv6_loopback_literal_is_blocked(monkeypatch, redis_client):
    delivery_id = await _make_delivery("http://[::1]:8080/in")
    _forbid_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    delivery = await _load(delivery_id)
    assert delivery.status == "failed"
    assert "blocked" in delivery.last_error.lower()


async def test_hostname_resolving_to_ipv6_loopback_is_blocked(monkeypatch, redis_client):
    delivery_id = await _make_delivery("https://hooks.example.com/in")
    monkeypatch.setattr("app.services.auth._getaddrinfo", _resolver("::1"))
    _forbid_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    delivery = await _load(delivery_id)
    assert delivery.status == "failed"
    assert "blocked" in delivery.last_error.lower()


async def test_public_ipv6_literal_is_delivered_with_valid_host_header(
    monkeypatch, redis_client
):
    delivery_id = await _make_delivery(f"http://[{PUBLIC_IPV6}]:8080/in")
    seen = _capture_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == PUBLIC_IPV6
    assert request.url.port == 8080
    assert request.headers["Host"] == f"[{PUBLIC_IPV6}]:8080"

    delivery = await _load(delivery_id)
    assert delivery.status == "delivered"


async def test_hostname_with_public_ipv6_answer_is_pinned_to_it(monkeypatch, redis_client):
    delivery_id = await _make_delivery("https://hooks.example.com/in")
    monkeypatch.setattr("app.services.auth._getaddrinfo", _resolver(PUBLIC_IPV6))
    seen = _capture_client(monkeypatch)

    await _dispatch_delivery(delivery_id, redis_client)

    assert seen[0].url.host == PUBLIC_IPV6
    assert seen[0].headers["Host"] == "hooks.example.com"
    assert seen[0].extensions["sni_hostname"] == "hooks.example.com"


async def test_server_error_schedules_retry(monkeypatch, redis_client):
    delivery_id = await _make_delivery("https://hooks.example.com/in")
    _capture_client(monkeypatch, status_code=500)

    await _dispatch_delivery(delivery_id, redis_client)

    delivery = await _load(delivery_id)
    assert delivery.status == "pending"
    assert delivery.attempt_count == 1
    assert delivery.next_retry_at is not None
    assert delivery.next_retry_at >= datetime.now(timezone.utc) - worker.timedelta(seconds=5)
    assert "500" in delivery.last_error


async def test_fourth_failure_marks_delivery_failed(monkeypatch, redis_client):
    delivery_id = await _make_delivery("https://hooks.example.com/in")
    seen = _capture_client(monkeypatch, status_code=500)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        await _dispatch_delivery(delivery_id, redis_client)
        delivery = await _load(delivery_id)
        assert delivery.attempt_count == attempt
        if attempt < MAX_ATTEMPTS:
            assert delivery.status == "pending"

    assert delivery.status == "failed"
    assert len(seen) == MAX_ATTEMPTS
    assert f"attempt {MAX_ATTEMPTS} of {MAX_ATTEMPTS}" in delivery.last_error
