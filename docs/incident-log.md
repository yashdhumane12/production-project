# Incident Log — TaskMaster Production Project

This is the most important file in this repo.
Every time something broke, how you found it, and what you changed.

**This is what separates a real engineer from someone who just ran tutorials.**

---

## Incident #001 — Redis Cache Not Invalidating on Update
**Date:** 2024-10-05  
**Severity:** P3 (data inconsistency, no downtime)

### What happened
After doing `PUT /tasks/1`, subsequent `GET /tasks` was still returning the old title for 60 seconds.

### How I found it
Noticed it while manually testing the API — updated a task, listed all tasks, old data came back. Checked Redis:
```bash
docker exec taskmaster-redis redis-cli get "tasks:all"
# Still had old data
```

### Root cause
`update_task()` was deleting `tasks:{id}` but NOT deleting `tasks:all` (the list cache).

### Fix
```python
# Before (buggy)
r.delete(f"tasks:{tid}")

# After (fixed)
r.delete(f"tasks:{tid}", "tasks:all")
```

### What I learned
- Cache invalidation is hard — every write path must invalidate ALL related cache keys
- The list cache (`tasks:all`) and individual cache (`tasks:1`) are separate keys
- Test this explicitly: write → verify cache is gone → read again

---

## Incident #002 — Gunicorn Workers Exhausted Under Load
**Date:** 2024-10-06  
**Severity:** P2 (high latency, partial 503s)

### What happened
During k6 load test at 100 VUs, P95 latency jumped from 80ms to 4.2s. Some requests started returning 503.

### How I found it
k6 output showed `p(95)` threshold breached. Checked container:
```bash
docker stats taskmaster-app
# CPU: 98%, Memory: 210MB/256MB
```

Checked logs:
```bash
docker logs taskmaster-app --tail 50
# [CRITICAL] WORKER TIMEOUT: worker with pid 23 ...
```

### Root cause
Gunicorn was configured with 2 workers. Each worker blocks on DB queries. At 100 concurrent users, workers were exhausted — new requests queued up.

### Fix
1. Increased workers from 2 to 4: `--workers 4`
2. Switched from sync to gevent workers: `--worker-class gevent`
3. Added connection pool size increase: `maxconn=20`

### What I learned
- Sync Gunicorn workers = 1 request per worker at a time
- Gevent workers handle many concurrent requests per worker (non-blocking I/O)
- DB connection pool must match worker count × threads

---

## Incident #003 — Kubernetes Pod OOMKilled After Deploy
**Date:** 2024-10-08  
**Severity:** P2 (rolling restart loop)

### What happened
After deploying to k8s, pods kept restarting. `kubectl get pods` showed `OOMKilled` in the RESTARTS column.

### How I found it
```bash
kubectl get pods
# NAME                         READY   STATUS      RESTARTS
# taskmaster-app-xxx           0/1     OOMKilled   3

kubectl describe pod taskmaster-app-xxx
# Last State: Terminated (OOMKilled)
# Limits: memory: 128Mi
```

### Root cause
Memory limit was set to 128Mi. Flask + gunicorn + prometheus-client was using ~140MB at startup.

### Fix
Increased memory limit in `helm/taskmaster/values.yaml`:
```yaml
# Before
limits:
  memory: 128Mi

# After
limits:
  memory: 256Mi
```

### What I learned
- Always set memory limits higher than measured usage — include headroom for spikes
- `kubectl top pods` shows live memory usage
- OOMKill is sudden — no warning, pod just dies

---

## Template for new incidents

### Incident #00X — [Title]
**Date:** YYYY-MM-DD  
**Severity:** P1/P2/P3

**What happened:**  
**How I found it:**  
**Root cause:**  
**Fix:**  
**What I learned:**  

---
