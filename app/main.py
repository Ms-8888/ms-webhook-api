import asyncio
import logging

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config import settings
from app.database import engine
from app.database import Base
from app.dependencies import set_redis
from app.routers import endpoints, events, health
from app.services.worker import dispatch_worker, retry_worker

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Webhook Delivery API", version="1.0.0")
app.include_router(endpoints.router)
app.include_router(events.router)
app.include_router(health.router)

_tasks: list[asyncio.Task] = []


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    set_redis(redis)

    _tasks.append(asyncio.create_task(dispatch_worker(redis)))
    _tasks.append(asyncio.create_task(retry_worker(redis)))


@app.on_event("shutdown")
async def shutdown():
    for task in _tasks:
        task.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
