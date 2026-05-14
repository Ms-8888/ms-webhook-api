import hashlib
import ipaddress
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def resolve_tenant(api_key: str, db: AsyncSession) -> Tenant | None:
    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(Tenant).where(Tenant.api_key_hash == key_hash, Tenant.is_active.is_(True))
    )
    return result.scalar_one_or_none()


def validate_endpoint_url(url: str) -> str | None:
    """Return an error message if the URL is unsafe, else None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return "URL must use http or https"

    hostname = parsed.hostname
    if not hostname:
        return "Invalid URL: missing hostname"

    if hostname in ("localhost", "127.0.0.1", "::1"):
        return "URL must not point to localhost"

    try:
        addr = ipaddress.ip_address(hostname)
        for network in _PRIVATE_NETWORKS:
            if addr in network:
                return "URL must not point to a private IP address"
    except ValueError:
        pass  # hostname is a domain name, not an IP — fine

    return None
