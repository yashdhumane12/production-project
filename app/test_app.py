"""Unit tests — run without real DB/Redis using mocks."""
import json
import pytest
from unittest.mock import patch, MagicMock

# Patch DB + Redis before importing app
with patch("psycopg2.pool.ThreadedConnectionPool"), patch("redis.Redis"):
    from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ready"


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"http_requests_total" in r.data


def test_create_task_missing_title(client):
    r = client.post("/tasks",
                    data=json.dumps({}),
                    content_type="application/json")
    assert r.status_code == 400
    assert "title required" in r.get_json()["error"]
