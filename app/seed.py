"""
Run with: python -m app.seed

Creates a demo tenant and prints the raw API key.
Run `alembic upgrade head` first to create the schema.
"""
import asyncio

from app.database import AsyncSessionLocal
from app.models import Tenant


async def main():
    raw_key = Tenant.generate_api_key()
    key_hash = Tenant.hash_api_key(raw_key)

    async with AsyncSessionLocal() as db:
        tenant = Tenant(name="Demo Tenant", api_key_hash=key_hash)
        db.add(tenant)
        await db.commit()

    print("Demo tenant created.")
    print(f"API Key: {raw_key}")
    print("Use this as the X-API-Key header in all requests.")


if __name__ == "__main__":
    asyncio.run(main())
