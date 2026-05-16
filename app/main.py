import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError

from app.config import settings
from app.database import Base, engine
from app.dependencies import set_redis
from app.routers import endpoints, events, health
from app.services.worker import dispatch_worker, retry_worker

logging.basicConfig(level=logging.INFO)

_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_keepalive=True,
        health_check_interval=30,
        retry=Retry(ExponentialBackoff(), 3),
        retry_on_error=[ConnectionError, TimeoutError],
    )
    set_redis(redis)

    _tasks.append(asyncio.create_task(dispatch_worker(redis)))
    _tasks.append(asyncio.create_task(retry_worker(redis)))

    yield

    for task in _tasks:
        task.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    await redis.aclose()


app = FastAPI(title="Webhook Delivery API", version="1.0.0", lifespan=lifespan)
app.include_router(endpoints.router)
app.include_router(events.router)
app.include_router(health.router)
