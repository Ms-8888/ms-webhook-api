from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Supabase transaction pooler requires prepared statements disabled
_connect_args = (
    {"prepared_statement_cache_size": 0}
    if "pooler.supabase.com" in settings.database_url
    else {}
)
engine = create_async_engine(settings.database_url, connect_args=_connect_args, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
