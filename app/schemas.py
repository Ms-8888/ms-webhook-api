from datetime import datetime

from pydantic import BaseModel, HttpUrl


class EndpointCreate(BaseModel):
    url: HttpUrl
    description: str | None = None


class EndpointOut(BaseModel):
    id: int
    url: str
    description: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    event_type: str
    payload: dict


class EventOut(BaseModel):
    id: int
    event_type: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class DeliveryOut(BaseModel):
    id: int
    endpoint_id: int
    endpoint_url: str
    status: str
    attempt_count: int
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MetricsOut(BaseModel):
    total_events_today: int
    delivery_success_rate: float
    queue_depth: int
    failed_deliveries_24h: int


class HealthOut(BaseModel):
    status: str
    db: str
    redis: str
