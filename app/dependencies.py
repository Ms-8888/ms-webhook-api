from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Tenant
from app.services.auth import resolve_tenant

_redis: Redis | None = None


def set_redis(r: Redis) -> None:
    global _redis
    _redis = r


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis client has not been initialized")
    return _redis


async def get_current_tenant(
    x_api_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    tenant = await resolve_tenant(x_api_key, db)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return tenant


async def check_rate_limit(
    tenant: Tenant = Depends(get_current_tenant),
    redis: Redis = Depends(get_redis),
) -> Tenant:
    key = f"rate:{tenant.id}:events"
    # SET NX initializes the key with TTL atomically; INCR then counts requests.
    # Using a pipeline avoids the race where INCR succeeds but EXPIRE never runs.
    async with redis.pipeline(transaction=True) as pipe:
        await pipe.set(key, 0, ex=3600, nx=True)
        await pipe.incr(key)
        await pipe.ttl(key)
        _, count, ttl = await pipe.execute()
    if count > 100:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: 100 events per hour",
            headers={"Retry-After": str(max(int(ttl), 1))},
        )
    return tenant
