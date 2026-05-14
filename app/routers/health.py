from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_tenant, get_redis
from app.models import Delivery, Event, Tenant
from app.schemas import HealthOut, MetricsOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    db_status = "ok"
    redis_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    try:
        await redis.ping()
    except Exception:
        redis_status = "error"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return HealthOut(status=overall, db=db_status, redis=redis_status)


@router.get("/metrics", response_model=MetricsOut)
async def metrics(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    total_events = await db.scalar(
        select(func.count(Event.id)).where(Event.created_at >= day_ago)
    ) or 0

    total_deliveries = await db.scalar(
        select(func.count(Delivery.id)).where(Delivery.created_at >= day_ago)
    ) or 0

    delivered = await db.scalar(
        select(func.count(Delivery.id)).where(
            Delivery.created_at >= day_ago, Delivery.status == "delivered"
        )
    ) or 0

    failed = await db.scalar(
        select(func.count(Delivery.id)).where(
            Delivery.created_at >= day_ago, Delivery.status == "failed"
        )
    ) or 0

    success_rate = round(delivered / total_deliveries, 4) if total_deliveries > 0 else 1.0
    queue_depth = await redis.llen("deliveries:queue")

    return MetricsOut(
        total_events_today=total_events,
        delivery_success_rate=success_rate,
        queue_depth=queue_depth,
        failed_deliveries_24h=failed,
    )


@router.get("/metrics/chart")
async def metrics_chart(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    result = await db.execute(
        select(
            func.date_trunc("hour", Delivery.created_at).label("hour"),
            func.count(Delivery.id).label("total"),
            func.sum(case((Delivery.status == "delivered", 1), else_=0)).label("delivered"),
        )
        .join(Event, Delivery.event_id == Event.id)
        .where(Delivery.created_at >= day_ago, Event.tenant_id == tenant.id)
        .group_by(func.date_trunc("hour", Delivery.created_at))
        .order_by(func.date_trunc("hour", Delivery.created_at))
    )
    rows = {r.hour.replace(tzinfo=timezone.utc): (r.delivered or 0, r.total) for r in result.all()}

    data = []
    for i in range(24):
        h = (day_ago + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        delivered, total = rows.get(h, (0, 0))
        rate = round(delivered / total, 4) if total > 0 else 1.0
        data.append({"hour": h.strftime("%H:%M"), "rate": rate})
    return data
