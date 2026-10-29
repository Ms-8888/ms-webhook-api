import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from redis.asyncio import Redis
from sqlalchemy import and_, or_, select

from app.database import AsyncSessionLocal
from app.models import Delivery, Endpoint
from app.services.auth import resolve_public_addresses
from app.services.dispatcher import QUEUE_KEY

logger = logging.getLogger(__name__)

RETRY_DELAYS = {1: 0, 2: 60, 3: 300, 4: 1800}
MAX_ATTEMPTS = 4
DELIVERY_TIMEOUT = 10.0
UNQUEUED_AFTER_SECONDS = 120


def _sign_payload(secret: str, payload: bytes, timestamp: str) -> str:
    message = f"{timestamp}.".encode() + payload
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _pin_request(url: str, address: str) -> tuple[httpx.URL, dict[str, str], dict[str, str]]:
    """Connect to the address that was checked, not to whatever the name resolves to now."""
    original = httpx.URL(url)
    host_header = original.host if original.port is None else f"{original.host}:{original.port}"
    pinned = original.copy_with(host=address)
    return pinned, {"Host": host_header}, {"sni_hostname": original.host}


async def _dispatch_delivery(delivery_id: int, redis: Redis) -> None:
    async with AsyncSessionLocal() as db:
        delivery = await db.get(Delivery, delivery_id, populate_existing=True)
        if not delivery or delivery.status == "delivered":
            return

        endpoint = await db.get(Endpoint, delivery.endpoint_id)
        if not endpoint or not endpoint.is_active:
            delivery.status = "failed"
            delivery.last_error = "Endpoint no longer active"
            await db.commit()
            return

        await db.refresh(delivery, ["event"])
        payload_bytes = json.dumps(delivery.event.payload).encode()
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signature = _sign_payload(endpoint.secret, payload_bytes, timestamp)

        delivery.attempt_count += 1

        try:
            original = httpx.URL(endpoint.url)
            port = original.port or (443 if original.scheme == "https" else 80)
            addresses, blocked = await resolve_public_addresses(original.host, port)
            if blocked:
                delivery.status = "failed"
                delivery.last_error = f"Delivery blocked: {blocked}"
                await db.commit()
                return
            pinned_url, host_headers, extensions = _pin_request(endpoint.url, addresses[0])

            async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT, follow_redirects=False) as client:
                response = await client.post(
                    pinned_url,
                    content=payload_bytes,
                    extensions=extensions,
                    headers={
                        **host_headers,
                        "Content-Type": "application/json",
                        "X-Webhook-Signature": signature,
                        "X-Webhook-Timestamp": timestamp,
                        "X-Event-Type": delivery.event.event_type,
                    },
                )
            response.raise_for_status()
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(timezone.utc)

        except Exception as exc:
            if isinstance(exc, httpx.TimeoutException):
                error_msg = f"Connection timeout after {int(DELIVERY_TIMEOUT * 1000)}ms"
            else:
                error_msg = str(exc)
            delivery.last_error = (
                f"{error_msg} — attempt {delivery.attempt_count} of {MAX_ATTEMPTS}"
            )

            if delivery.attempt_count >= MAX_ATTEMPTS:
                delivery.status = "failed"
            else:
                delay = RETRY_DELAYS.get(delivery.attempt_count + 1, 1800)
                delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

        await db.commit()


async def dispatch_worker(redis: Redis) -> None:
    """Task 1: Poll Redis queue for new deliveries and dispatch them."""
    logger.info("Dispatch worker started")
    while True:
        try:
            item = await redis.lpop(QUEUE_KEY)
            if item:
                await _dispatch_delivery(int(item), redis)
            else:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Dispatch worker error: %s", exc)
            await asyncio.sleep(5)


async def requeue_due_deliveries(redis: Redis) -> int:
    """Queue deliveries that are due for a retry, or that never reached the queue."""
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        never_queued_before = now - timedelta(seconds=UNQUEUED_AFTER_SECONDS)
        result = await db.execute(
            select(Delivery.id).where(
                Delivery.status == "pending",
                Delivery.attempt_count < MAX_ATTEMPTS,
                or_(
                    and_(Delivery.attempt_count > 0, Delivery.next_retry_at <= now),
                    and_(Delivery.attempt_count == 0, Delivery.created_at <= never_queued_before),
                ),
            )
        )
        ids = result.scalars().all()
        if ids:
            await redis.rpush(QUEUE_KEY, *[str(i) for i in ids])
        return len(ids)


async def retry_worker(redis: Redis) -> None:
    """Task 2: Every 30s, re-queue due retries and deliveries that never reached the queue."""
    logger.info("Retry worker started")
    while True:
        try:
            await asyncio.sleep(30)
            count = await requeue_due_deliveries(redis)
            if count:
                logger.info("Re-queued %d deliveries", count)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Retry worker error: %s", exc)
