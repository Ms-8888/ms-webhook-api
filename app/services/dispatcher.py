from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Delivery, Endpoint, Event

QUEUE_KEY = "deliveries:queue"


async def queue_event(event: Event, db: AsyncSession) -> list[int]:
    """Create one delivery row per active endpoint and return the IDs.

    Caller is responsible for pushing IDs to Redis after db.commit() so the
    worker cannot race and read a delivery that hasn't been committed yet.
    """
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
    return result.scalars().all()
