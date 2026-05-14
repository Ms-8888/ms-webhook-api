from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import check_rate_limit, get_current_tenant, get_redis
from app.models import Delivery, Endpoint, Event, Tenant
from app.schemas import DeliveryOut, EventCreate, EventOut
from app.services.dispatcher import QUEUE_KEY, queue_event

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def fire_event(
    body: EventCreate,
    tenant: Tenant = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    event = Event(tenant_id=tenant.id, event_type=body.event_type, payload=body.payload)
    db.add(event)
    await db.flush()
    delivery_ids = await queue_event(event, db)
    await db.commit()
    if delivery_ids:
        await redis.rpush(QUEUE_KEY, *[str(d) for d in delivery_ids])
    return {"event_id": event.id, "queued_deliveries": len(delivery_ids)}


@router.get("", response_model=list[EventOut])
async def list_events(
    page: int = 1,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    page_size = 20
    result = await db.execute(
        select(Event)
        .where(Event.tenant_id == tenant.id)
        .order_by(Event.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


@router.get("/{event_id}/deliveries", response_model=list[DeliveryOut])
async def get_deliveries(
    event_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Delivery, Endpoint.url)
        .join(Endpoint, Delivery.endpoint_id == Endpoint.id)
        .join(Event, Delivery.event_id == Event.id)
        .where(Delivery.event_id == event_id, Event.tenant_id == tenant.id)
        .order_by(Delivery.created_at.asc())
    )
    rows = result.all()
    return [
        DeliveryOut(
            id=d.id,
            endpoint_id=d.endpoint_id,
            endpoint_url=url,
            status=d.status,
            attempt_count=d.attempt_count,
            last_error=d.last_error,
            delivered_at=d.delivered_at,
            created_at=d.created_at,
        )
        for d, url in rows
    ]
