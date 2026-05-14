from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_tenant
from app.models import Endpoint, Tenant
from app.schemas import EndpointCreate, EndpointOut
from app.services.auth import validate_endpoint_url

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


@router.post("", response_model=EndpointOut, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: EndpointCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    url_str = str(body.url)
    error = validate_endpoint_url(url_str)
    if error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)

    endpoint = Endpoint(tenant_id=tenant.id, url=url_str, description=body.description)
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


@router.get("", response_model=list[EndpointOut])
async def list_endpoints(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Endpoint)
        .where(Endpoint.tenant_id == tenant.id, Endpoint.is_active.is_(True))
        .order_by(Endpoint.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_endpoint(
    endpoint_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    endpoint = await db.get(Endpoint, endpoint_id)
    if not endpoint or endpoint.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    endpoint.is_active = False
    await db.commit()
