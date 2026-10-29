# ms-webhook-api

An async webhook delivery API built with FastAPI, PostgreSQL and Redis. Companion dashboard: [ms-webhook-ui](https://github.com/Ms-8888/ms-webhook-ui).

## Problem

An application that notifies customers of events (an order was created, a payment failed) has to call their servers. Those servers are sometimes down, slow or wrong. Sending the request inside the user's own request blocks it, loses the event when the customer's server is down, and gives no way to prove what was sent.

## Solution

Your application sends one event to this API and gets `202 Accepted` back immediately. A background worker then delivers it to every registered endpoint:

- **Signed:** each request carries an HMAC-SHA256 signature and timestamp so the receiver can verify the sender.
- **Retried:** failures are retried at +1, +5 and +30 minutes; the retry state is stored in PostgreSQL, so it survives a restart.
- **Tracked:** every attempt, error and final status is stored and readable through the API.
- **Guarded:** endpoint URLs pointing at private or local addresses are rejected (SSRF check), API keys are stored hashed, and each tenant is limited to 100 events per hour.

---

## Live Demo

**API:** `https://ms-webhook-api.onrender.com`  
**Demo API key:** `314b254a8cd3d91f4c08888d8b5544db3c6d24d8b17528fb10fd2d4375956421` <!-- gitleaks:allow -->  
**Dashboard:** [live dashboard](https://ms-8888.github.io/ms-webhook-ui/) (paste the key into Settings)

> Hosted on Render free tier, so the first request may take about 30 seconds to wake the instance.  
> This is a shared public key for a demo tenant: send no real data, and expect other visitors' test events in the list. Each tenant is limited to 100 events per hour.

Try it:

```bash
curl https://ms-webhook-api.onrender.com/health

curl -X POST https://ms-webhook-api.onrender.com/events   -H "X-API-Key: 314b254a8cd3d91f4c08888d8b5544db3c6d24d8b17528fb10fd2d4375956421"   -H "Content-Type: application/json"   -d '{"event_type": "order.created", "payload": {"order_id": 42}}'

curl https://ms-webhook-api.onrender.com/events -H "X-API-Key: 314b254a8cd3d91f4c08888d8b5544db3c6d24d8b17528fb10fd2d4375956421"
```

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
docker compose -f deploy/docker-compose.yml exec app python -m app.seed   # creates a demo tenant, prints your API key
curl localhost:8000/health   # {"status":"ok","db":"ok","redis":"ok"}
```

The app creates its tables on startup. Alembic migrations (`alembic upgrade head`) are what the Render deploy runs; do not run them on a database the app has already started against.

If ports 5432 or 6379 are already in use on your machine, change the left-hand port numbers in `deploy/docker-compose.yml`.

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

Example response (illustrative values):

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
X-Webhook-Signature: sha256=<hmac_sha256(endpoint_secret, "<timestamp>." + payload)>
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

## Limitations

- The dispatch and retry workers run inside the API process; there is no separate worker service or horizontal scaling.
- The hosted demo runs on free tiers (Render, Neon, Upstash), so expect cold starts.
- Tested with the 10 automated tests in `tests/` and manual runs; there are no load-test numbers.

---

## Stack

Python · FastAPI · PostgreSQL 16 · Redis 7 · SQLAlchemy (async) · Alembic · Docker · GitHub Actions
