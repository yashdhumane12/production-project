# Architecture — TaskMaster

## System Design

```
Internet
    │
    ▼
Nginx (reverse proxy + TLS termination)
    │
    ▼
TaskMaster App (Flask, 2-8 pods, HPA)
    ├── PostgreSQL (primary, private subnet)
    │       └── Redis (cache, 60s TTL)
    └── /metrics
            │
            ▼
        Prometheus → Grafana (dashboards)
                   → Alertmanager → Email/Slack
```

## Design Decisions

### Why Redis cache?
`GET /tasks` is the most frequent call. Without cache, every request hits PostgreSQL.
With 60s TTL cache, 100 req/s means ~1 DB query per minute for list endpoint.

**Tradeoff:** 60s stale data window. Acceptable for a task list, not acceptable for financial data.

### Why connection pool?
`psycopg2.ThreadedConnectionPool(minconn=2, maxconn=10)` — reuse connections instead of creating new TCP + auth handshake per request.
Without pool: ~20ms per request just for connection setup.
With pool: <1ms, connection already established.

### Why non-root container?
If app code has a vulnerability that allows command execution, attacker gets `appuser` (no privileges) instead of `root` (full system access).

### Why HPA (2-8 pods)?
Scale out during load spikes (scale up pod count), scale down during quiet periods (save cost).
Target: 70% CPU utilization — pods scale before they become saturated.

### Why rolling update strategy?
`maxSurge: 1, maxUnavailable: 0` — always have full capacity during deploy.
New pod comes up → health check passes → old pod terminates.
Zero downtime.

## What I would change in production

1. **PgBouncer** — connection pooler in front of Postgres (handles thousands of connections, Postgres handles ~100)
2. **Read replicas** — offload `GET /tasks` DB queries to replica
3. **Redis Sentinel / Cluster** — HA for cache
4. **Distributed tracing** — OpenTelemetry to trace requests across services
5. **mTLS between services** — Istio service mesh
