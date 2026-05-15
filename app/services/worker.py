import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from redis.asyncio import Redis
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Delivery, Endpoint
from app.services.dispatcher import QUEUE_KEY

logger = logging.getLogger(__name__)

RETRY_DELAYS = {1: 0, 2: 60, 3: 300, 4: 1800}
MAX_ATTEMPTS = 4
DELIVERY_TIMEOUT = 10.0


def _sign_payload(secret: str, payload: bytes, timestamp: str) -> str:
    message = f"{timestamp}.".encode() + payload
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


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
            async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
                response = await client.post(
                    endpoint.url,
                    content=payload_bytes,
                    headers={
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
            error_msg = f"Connection timeout after {int(DELIVERY_TIMEOUT * 1000)}ms" if isinstance(exc, httpx.TimeoutException) else str(exc)
            delivery.last_error = f"{error_msg} — attempt {delivery.attempt_count} of {MAX_ATTEMPTS}"

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


async def retry_worker(redis: Redis) -> None:
    """Task 2: Every 30s, re-queue pending deliveries whose next_retry_at has passed."""
    logger.info("Retry worker started")
    while True:
        try:
            await asyncio.sleep(30)
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                result = await db.execute(
                    select(Delivery.id).where(
                        Delivery.status == "pending",
                        Delivery.next_retry_at <= now,
                        Delivery.attempt_count > 0,
                        Delivery.attempt_count < MAX_ATTEMPTS,
                    )
                )
                ids = result.scalars().all()
                if ids:
                    await redis.rpush(QUEUE_KEY, *[str(i) for i in ids])
                    logger.info("Re-queued %d deliveries for retry", len(ids))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Retry worker error: %s", exc)
