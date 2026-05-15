import os
import secrets

import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.dependencies import set_redis
from app.main import app
from app.models import Tenant

TEST_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/webhooks_test")
TEST_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="session")
async def redis_client():
    client = aioredis.from_url(TEST_REDIS_URL, decode_responses=True)
    set_redis(client)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def flush_redis(redis_client):
    yield
    await redis_client.flushdb()


@pytest_asyncio.fixture
async def tenant(db: AsyncSession):
    raw_key = secrets.token_hex(16)
    t = Tenant(name="Test Tenant", api_key_hash=Tenant.hash_api_key(raw_key))
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t, raw_key


@pytest_asyncio.fixture
async def client(db: AsyncSession, redis_client):
    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
