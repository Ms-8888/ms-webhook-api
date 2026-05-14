# ms-webhook-api

A production-ready async webhook delivery API. Register endpoint URLs, fire events, and the system fans out signed HTTP POST requests to all your endpoints — with automatic retry logic and full delivery tracking.

Built with FastAPI, PostgreSQL, and Redis. Companion dashboard: [ms-webhook-ui](https://github.com/Ms-8888/ms-webhook-ui).

---

## Architecture

```
POST /events
     │
     ▼
 FastAPI (validates, writes event row)
     │
     ▼
 Redis queue (deliveries:queue)
     │
     ▼
 Async worker (dispatches HTTP POST to each endpoint)
     │
     ├─ 200 OK  → status: delivered
     └─ failure → retry: +1min → +5min → +30min → failed
```

---

## Quick Start

**Prerequisites:** Docker and Docker Compose.

```bash
git clone https://github.com/Ms-8888/ms-webhook-api
cd ms-webhook-api
cp .env.example .env
docker compose -f deploy/docker-compose.yml up -d
python -m app.seed       # creates demo tenant, prints your API key
```

---

## Walkthrough

### 1. Register a webhook endpoint

```bash
curl -X POST http://localhost:8000/endpoints \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://webhook.site/your-id", "description": "Test endpoint"}'
```

### 2. Fire an event

```bash
curl -X POST http://localhost:8000/events \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"event_type": "order.created", "payload": {"order_id": 42, "amount": 99.99}}'
```

Returns `202 Accepted` immediately — delivery happens asynchronously.

### 3. Check delivery status

```bash
curl http://localhost:8000/events/1/deliveries \
  -H "X-API-Key: <your-key>"
```

```json
[
  {
    "id": 1,
    "endpoint_url": "https://webhook.site/your-id",
    "status": "delivered",
    "attempt_count": 1,
    "last_error": null,
    "delivered_at": "2025-01-15T10:23:45Z"
  }
]
```

### 4. Check metrics

```bash
curl http://localhost:8000/metrics -H "X-API-Key: <your-key>"
```

```json
{
  "total_events_today": 847,
  "delivery_success_rate": 0.94,
  "queue_depth": 3,
  "failed_deliveries_24h": 12
}
```

---

## Retry Logic

Every outbound request is signed with HMAC-SHA256 and retried on failure:

| Attempt | Delay |
|---------|-------|
| 1 | Immediate |
| 2 | +1 minute |
| 3 | +5 minutes |
| 4 | +30 minutes |

After 4 failed attempts the delivery is marked `failed` and the error saved. Retry state lives in PostgreSQL — survives restarts.

Each delivery includes:
```
X-Webhook-Signature: sha256=<hmac_sha256(endpoint_secret, payload)>
X-Webhook-Timestamp: <unix_timestamp>
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/endpoints` | Register a webhook URL |
| `GET` | `/endpoints` | List your endpoints |
| `DELETE` | `/endpoints/{id}` | Remove an endpoint |
| `POST` | `/events` | Fire an event (202 Accepted) |
| `GET` | `/events` | List recent events |
| `GET` | `/events/{id}/deliveries` | Delivery status per endpoint |
| `GET` | `/health` | DB + Redis connectivity |
| `GET` | `/metrics` | Delivery stats |

Auth: `X-API-Key` header on all routes. Rate limit: 100 events/hour per tenant.

---

## Stack

Python · FastAPI · PostgreSQL 16 · Redis 7 · SQLAlchemy (async) · Alembic · Docker · GitHub Actions
