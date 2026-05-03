import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB_PATH = ROOT / "fastapi_app" / "tests" / "test_observability.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402


client = None


def setup_function():
    global client
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
    os.environ["RATE_LIMIT_REQUESTS"] = "2"
    os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "60"
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    importlib.reload(db_module)
    importlib.reload(models_module)
    importlib.reload(crud_module)
    importlib.reload(main_module)
    db_module.Base.metadata.create_all(bind=db_module.engine)
    client = TestClient(main_module.app)


def teardown_function():
    global client
    if client is not None:
        client.close()
        client = None
    close_all_sessions()
    db_module.Base.metadata.drop_all(bind=db_module.engine)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    os.environ.pop("RATE_LIMIT_REQUESTS", None)
    os.environ.pop("RATE_LIMIT_WINDOW_SECONDS", None)


def test_health_readiness_and_metrics_endpoints_work():
    health = client.get("/healthz")
    ready = client.get("/readyz")
    metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text
    assert "app_uptime_seconds" in metrics.text


def test_request_headers_and_security_headers_are_added():
    response = client.get("/users/", headers={"X-Request-ID": "req-test-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-123"
    assert "X-Process-Time-Ms" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-RateLimit-Limit"] == "2"


def test_rate_limiting_returns_429_and_retry_headers():
    first = client.get("/users/", headers={"x-forwarded-for": "203.0.113.10"})
    second = client.get("/users/", headers={"x-forwarded-for": "203.0.113.10"})
    third = client.get("/users/", headers={"x-forwarded-for": "203.0.113.10"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["Retry-After"]
    assert third.headers["X-RateLimit-Limit"] == "2"
    assert third.headers["X-RateLimit-Remaining"] == "0"
    assert third.json()["detail"] == "Rate limit exceeded. Please retry later."
