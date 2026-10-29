import asyncio
import hashlib
import ipaddress
import socket
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant

def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def resolve_tenant(api_key: str, db: AsyncSession) -> Tenant | None:
    key_hash = hash_api_key(api_key)
    result = await db.execute(
        select(Tenant).where(Tenant.api_key_hash == key_hash, Tenant.is_active.is_(True))
    )
    return result.scalar_one_or_none()


BLOCKED_MESSAGE = "URL must not point to a private or internal address"


def is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not a normal public unicast address."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (not addr.is_global) or addr.is_multicast


async def _getaddrinfo(host: str, port: int):
    return await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)


async def resolve_public_addresses(hostname: str, port: int) -> tuple[list[str], str | None]:
    """Resolve hostname and return (addresses, error). Every address must be public."""
    host = hostname.strip("[]")
    if host.lower() == "localhost":
        return [], "URL must not point to localhost"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if is_blocked_address(literal):
            return [], BLOCKED_MESSAGE
        return [str(literal)], None

    try:
        infos = await _getaddrinfo(host, port)
    except OSError:
        return [], "URL hostname could not be resolved"

    addresses: list[str] = []
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if is_blocked_address(addr):
            return [], BLOCKED_MESSAGE
        if str(addr) not in addresses:
            addresses.append(str(addr))
    if not addresses:
        return [], "URL hostname could not be resolved"
    return addresses, None


async def validate_endpoint_url(url: str) -> str | None:
    """Return an error message if the URL is unsafe, else None."""
    try:
        parsed = urlparse(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return "URL must use http or https"

    if not parsed.hostname:
        return "Invalid URL: missing hostname"

    _, error = await resolve_public_addresses(parsed.hostname, port)
    return error
