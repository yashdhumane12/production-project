"""
TaskMaster API — Production-grade Flask app
Stack: Flask + PostgreSQL + Redis cache + prometheus-client metrics

Endpoints:
  GET    /health          liveness + dependency checks
  GET    /ready           readiness probe
  GET    /metrics         Prometheus scrape endpoint
  POST   /tasks           create task
  GET    /tasks           list tasks (Redis-cached, 60s TTL)
  GET    /tasks/<id>      get one task (Redis-cached)
  PUT    /tasks/<id>      update task (invalidates cache)
  DELETE /tasks/<id>      delete task (invalidates cache)
"""

import os, json, time, logging
from flask import Flask, request, jsonify, g
import psycopg2, psycopg2.pool
import redis
from prometheus_client import (
    Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","service":"taskmaster","msg":"%(message)s"}'
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Config from environment ───────────────────────────────────────────
PG_CONFIG = dict(
    host=os.getenv("POSTGRES_HOST", "postgres"),
    port=int(os.getenv("POSTGRES_PORT", 5432)),
    dbname=os.getenv("POSTGRES_DB", "taskmaster"),
    user=os.getenv("POSTGRES_USER", "appuser"),
    password=os.getenv("POSTGRES_PASSWORD", "secret"),
)
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
CACHE_TTL  = int(os.getenv("CACHE_TTL", 60))
APP_VERSION = os.getenv("APP_VERSION", "dev")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# ── Connection pool ───────────────────────────────────────────────────
pg_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10, **PG_CONFIG)
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True, socket_timeout=2)

# ── Prometheus metrics ────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)
DB_QUERY_LATENCY = Histogram(
    "db_query_duration_seconds",
    "Database query latency",
    ["operation"]
)
CACHE_HITS   = Counter("cache_hits_total",   "Redis cache hits",   ["key_prefix"])
CACHE_MISSES = Counter("cache_misses_total",  "Redis cache misses", ["key_prefix"])
ACTIVE_CONNS = Gauge("db_active_connections", "Active DB connections")
APP_INFO     = Gauge("app_info", "App metadata", ["version", "environment"])
APP_INFO.labels(version=APP_VERSION, environment=ENVIRONMENT).set(1)


# ── DB helpers ────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = pg_pool.getconn()
    return g.db

@app.teardown_appcontext
def release_db(_):
    db = g.pop("db", None)
    if db:
        pg_pool.putconn(db)

def init_db():
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id         SERIAL PRIMARY KEY,
                    title      VARCHAR(255) NOT NULL,
                    done       BOOLEAN DEFAULT FALSE,
                    priority   SMALLINT DEFAULT 2,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done);
            """)
        conn.commit()
        log.info("Database initialized")
    finally:
        pg_pool.putconn(conn)


# ── Middleware ────────────────────────────────────────────────────────
@app.before_request
def start_timer():
    g.start = time.time()

@app.after_request
def record_metrics(response):
    latency = time.time() - getattr(g, "start", time.time())
    endpoint = request.endpoint or "unknown"
    REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
    REQUEST_LATENCY.labels(request.method, endpoint).observe(latency)
    return response


# ── Health & metrics ──────────────────────────────────────────────────
@app.route("/health")
def health():
    checks, ok = {}, True
    # Postgres
    try:
        t = time.time()
        with get_db().cursor() as cur:
            cur.execute("SELECT 1")
        checks["postgres"] = {"status": "ok", "latency_ms": round((time.time()-t)*1000, 1)}
    except Exception as e:
        checks["postgres"] = {"status": "error", "error": str(e)}
        ok = False
    # Redis
    try:
        t = time.time()
        r.ping()
        checks["redis"] = {"status": "ok", "latency_ms": round((time.time()-t)*1000, 1)}
    except Exception as e:
        checks["redis"] = {"status": "error", "error": str(e)}
        ok = False
    # DB pool
    try:
        ACTIVE_CONNS.set(pg_pool._used.__len__() if hasattr(pg_pool, "_used") else 0)
    except Exception:
        pass
    return jsonify({
        "status": "healthy" if ok else "degraded",
        "version": APP_VERSION,
        "checks": checks
    }), 200 if ok else 503

@app.route("/ready")
def ready():
    return jsonify({"status": "ready"}), 200

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


# ── CRUD ──────────────────────────────────────────────────────────────
@app.route("/tasks", methods=["POST"])
def create_task():
    data = request.get_json(force=True) or {}
    if not data.get("title"):
        return jsonify({"error": "title required"}), 400
    t = time.time()
    with get_db().cursor() as cur:
        cur.execute(
            "INSERT INTO tasks(title,done,priority) VALUES(%s,%s,%s) "
            "RETURNING id,title,done,priority,created_at",
            (data["title"], data.get("done", False), data.get("priority", 2))
        )
        row = cur.fetchone()
    get_db().commit()
    DB_QUERY_LATENCY.labels("insert").observe(time.time() - t)
    r.delete("tasks:all")
    task = {"id": row[0], "title": row[1], "done": row[2],
            "priority": row[3], "created_at": str(row[4])}
    log.info("Created task %s", task["id"])
    return jsonify(task), 201

@app.route("/tasks", methods=["GET"])
def list_tasks():
    cached = r.get("tasks:all")
    if cached:
        CACHE_HITS.labels("tasks:all").inc()
        return jsonify(json.loads(cached))
    CACHE_MISSES.labels("tasks:all").inc()
    t = time.time()
    with get_db().cursor() as cur:
        cur.execute("SELECT id,title,done,priority,created_at FROM tasks ORDER BY priority,id")
        rows = cur.fetchall()
    DB_QUERY_LATENCY.labels("select_all").observe(time.time() - t)
    tasks = [{"id":r[0],"title":r[1],"done":r[2],"priority":r[3],"created_at":str(r[4])} for r in rows]
    r.setex("tasks:all", CACHE_TTL, json.dumps(tasks))
    return jsonify(tasks)

@app.route("/tasks/<int:tid>", methods=["GET"])
def get_task(tid):
    key = f"tasks:{tid}"
    cached = r.get(key)
    if cached:
        CACHE_HITS.labels("tasks:id").inc()
        return jsonify(json.loads(cached))
    CACHE_MISSES.labels("tasks:id").inc()
    with get_db().cursor() as cur:
        cur.execute("SELECT id,title,done,priority,created_at FROM tasks WHERE id=%s", (tid,))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    task = {"id":row[0],"title":row[1],"done":row[2],"priority":row[3],"created_at":str(row[4])}
    r.setex(key, CACHE_TTL, json.dumps(task))
    return jsonify(task)

@app.route("/tasks/<int:tid>", methods=["PUT"])
def update_task(tid):
    data = request.get_json(force=True) or {}
    with get_db().cursor() as cur:
        cur.execute(
            "UPDATE tasks SET title=%s,done=%s,priority=%s,updated_at=NOW() "
            "WHERE id=%s RETURNING id,title,done,priority,created_at",
            (data.get("title"), data.get("done"), data.get("priority", 2), tid)
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    get_db().commit()
    r.delete(f"tasks:{tid}", "tasks:all")
    return jsonify({"id":row[0],"title":row[1],"done":row[2],"priority":row[3],"created_at":str(row[4])})

@app.route("/tasks/<int:tid>", methods=["DELETE"])
def delete_task(tid):
    with get_db().cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE id=%s RETURNING id", (tid,))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    get_db().commit()
    r.delete(f"tasks:{tid}", "tasks:all")
    return jsonify({"deleted": tid})


if __name__ == "__main__":
    time.sleep(3)
    init_db()
    app.run(host="0.0.0.0", port=5000)
