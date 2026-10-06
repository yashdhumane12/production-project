# 🏭 TaskMaster — One Proper Production Project

A complete production-grade application. Every component has a reason. Every incident is documented.

> "One project where you can explain what broke, what you changed and why is better than 20 copied repos."

## What's inside

| Layer | Tech | Why |
|-------|------|-----|
| App | Flask + Python | Simple, readable API |
| Cache | Redis (60s TTL) | Reduce DB load on GET /tasks |
| Database | PostgreSQL | ACID, reliable, widely used |
| Container | Docker (multi-stage) | Small image, non-root user |
| Orchestration | Kubernetes + Helm | Rolling deploys, HPA auto-scaling |
| IaC | Terraform | Reproducible infrastructure |
| Config mgmt | Ansible | Server setup automation |
| CI/CD | GitHub Actions | Test → Build → Deploy → Rollback |
| Metrics | Prometheus | Scrapes /metrics every 15s |
| Dashboards | Grafana | Request rate, latency, errors, cache hits |
| Alerting | Alertmanager | Email on AppDown, HighErrorRate |
| Load testing | k6 | Find breaking point before users do |
| Backups | pg_dump + cron | Hourly, 7-day retention |
| Incident log | docs/incident-log.md | What broke and what you learned |

## Project structure

```
production-project/
├── app/                        Flask app with Redis cache + Prometheus metrics
│   ├── app.py                  CRUD API — 5 endpoints
│   ├── test_app.py             Unit tests (mocked DB/Redis)
│   ├── requirements.txt
│   └── Dockerfile              Multi-stage, non-root
├── helm/taskmaster/            Helm chart
│   ├── Chart.yaml
│   ├── values.yaml             All config in one place
│   └── templates/              Deployment, Service, HPA, Secret
├── terraform/
│   ├── bootstrap/              S3 + DynamoDB for remote state (run once)
│   ├── environments/prod/      VPC + EC2 + RDS
│   └── modules/vpc + ec2/      Reusable modules
├── monitoring/
│   ├── prometheus/             Scrape config + 4 alert rules
│   ├── alertmanager/           Email routing
│   └── grafana/                Auto-provisioned datasource
├── scripts/
│   ├── load-test.js            k6 ramp-up test
│   └── backup.sh               pg_dump + integrity check
├── docs/
│   ├── incident-log.md         3 real incidents documented
│   └── architecture.md         Design decisions explained
├── .github/workflows/ci-cd.yml Test → Build → Helm Deploy → Rollback
└── docker-compose.yml          Full local stack
```

## Quick start (local)

```bash
docker compose up -d --build

# Test the API
curl http://localhost:8080/health
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"Deploy to production","priority":1}'
curl http://localhost:8080/tasks

# Open Grafana
# http://localhost:3000  (admin / admin123)

# Run load test
k6 run scripts/load-test.js
```

## CI/CD flow

```
git push main
    ↓
1. pytest          — broken code never reaches Docker Hub
    ↓
2. docker build    — multi-stage, pushed with SHA tag
    ↓
3. helm lint       — chart validated before deploy
    ↓
4. helm upgrade    — rolling deploy, --atomic (auto-rollback on timeout)
    ↓
5. smoke test      — hit /health 10 times, must return 200
    ↓
Pass ✅ → done
Fail ❌ → helm rollback to previous revision
```

## Helm deploy (manual)

```bash
# Update image.repository in values.yaml first
helm upgrade --install taskmaster helm/taskmaster/ \
  --namespace production --create-namespace \
  --set image.tag=sha-abc1234 \
  --wait --timeout 5m

kubectl get pods -n production
kubectl logs -n production deploy/taskmaster-app
```

## Terraform (infrastructure)

```bash
# Bootstrap (once)
cd terraform/bootstrap && terraform init && terraform apply

# Deploy prod infrastructure
cd terraform/environments/prod
terraform init
terraform plan
terraform apply
```

## Monitoring

| URL | What |
|-----|------|
| http://localhost:9090 | Prometheus |
| http://localhost:3000 | Grafana (admin/admin123) |
| http://localhost:9093 | Alertmanager |

### Key Prometheus queries

```promql
# Request rate
sum(rate(http_requests_total[5m]))

# Error rate
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))

# P95 latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Cache hit ratio
rate(cache_hits_total[5m]) / (rate(cache_hits_total[5m]) + rate(cache_misses_total[5m]))

# DB query latency
histogram_quantile(0.95, rate(db_query_duration_seconds_bucket[5m]))
```

## Load testing

```bash
# Against local stack
k6 run scripts/load-test.js

# Against any URL
BASE_URL=http://your-server:8080 k6 run scripts/load-test.js
```

Stages: 10 → 50 → 100 VUs over 3 minutes.
Thresholds: P95 < 500ms, error rate < 5%.

## Backups

```bash
# Manual backup
bash scripts/backup.sh

# Verify restore works
PGDATABASE=taskmaster_restored bash scripts/backup.sh
```

## GitHub Secrets required

| Secret | Used for |
|--------|----------|
| `DOCKERHUB_USERNAME` | Push image |
| `DOCKERHUB_TOKEN` | Push image |
| `KUBECONFIG` | Deploy to cluster |

## Read this

**[docs/incident-log.md](docs/incident-log.md)** — 3 real incidents:
1. Redis cache not invalidating on updates
2. Gunicorn workers exhausted under load
3. Kubernetes pod OOMKilled after deploy

**[docs/architecture.md](docs/architecture.md)** — Why each design decision was made.

These two files are what make this project real. Anyone can copy a docker-compose.yml. Not everyone can explain what broke and why they changed it.

## License
MIT
