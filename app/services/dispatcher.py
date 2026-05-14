from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Delivery, Endpoint, Event

QUEUE_KEY = "deliveries:queue"


async def queue_event(event: Event, db: AsyncSession, redis: Redis) -> int:
    """Create one delivery row per active endpoint and push IDs onto Redis queue."""
    result = await db.execute(
        select(Endpoint).where(
            Endpoint.tenant_id == event.tenant_id,
            Endpoint.is_active.is_(True),
        )
    )
    endpoints = result.scalars().all()

    for endpoint in endpoints:
        delivery = Delivery(event_id=event.id, endpoint_id=endpoint.id)
        db.add(delivery)

    await db.flush()

    result = await db.execute(
        select(Delivery.id).where(Delivery.event_id == event.id)
    )
    delivery_ids = result.scalars().all()

    if delivery_ids:
        await redis.rpush(QUEUE_KEY, *[str(d) for d in delivery_ids])

    return len(delivery_ids)
