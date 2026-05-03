import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB_PATH = ROOT / "fastapi_app" / "tests" / "test_admin_usage_stats.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402


client = None


def setup_function():
    global client
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
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


def test_admin_usage_summary_aggregates_jobs_users_and_credits():
    user_1 = client.post("/users/", json={"email": "alpha@example.com"})
    user_2 = client.post("/users/", json={"email": "beta@example.com"})
    assert user_1.status_code == 201
    assert user_2.status_code == 201

    template = client.post(
        "/templates/",
        json={"name": "Promo Reel", "description": "Video template", "category": "video"},
    )
    assert template.status_code == 201
    template_id = template.json()["id"]

    user_2_id = user_2.json()["id"]
    with db_module.SessionLocal() as db:
        from fastapi_app.models import User

        beta = db.query(User).filter(User.id == user_2_id).first()
        beta.is_active = False
        db.commit()

    client.post(
        "/credit_packs/",
        json={"user_id": user_1.json()["id"], "pack_name": "100 credits", "credits": 100, "price": 29.99},
    )
    client.post(
        "/credit_packs/",
        json={"user_id": user_2_id, "pack_name": "50 credits", "credits": 50, "price": 14.99},
    )

    generation_payloads = [
        {
            "user_id": user_1.json()["id"],
            "template_id": template_id,
            "input_path": "/tmp/in-1.png",
            "output_path": "/tmp/out-1.mp4",
            "status": "completed",
            "credits_used": 12,
        },
        {
            "user_id": user_1.json()["id"],
            "template_id": template_id,
            "input_path": "/tmp/in-2.png",
            "status": "pending",
            "credits_used": 4,
        },
        {
            "user_id": user_2_id,
            "template_id": template_id,
            "input_path": "/tmp/in-3.png",
            "status": "failed",
            "credits_used": 3,
        },
    ]
    for payload in generation_payloads:
        response = client.post("/generations/", json=payload)
        assert response.status_code == 201

    response = client.get("/admin/reports/usage-summary")
    assert response.status_code == 200

    data = response.json()
    assert data == {
        "total_users": 2,
        "active_users": 1,
        "inactive_users": 1,
        "users_with_generations": 2,
        "users_with_credit_packs": 2,
        "total_jobs": 3,
        "jobs_by_status": {"completed": 1, "failed": 1, "pending": 1},
        "credits_spent": 19,
        "credits_earned": 150,
        "credits_refunded": 0,
        "credits_refunded_chargebacks": 0,
        "credits_balance": 131,
    }


def test_credit_report_uses_stored_generation_credit_usage_without_double_counting():
    user = client.post("/users/", json={"email": "solo@example.com"}).json()
    template = client.post(
        "/templates/",
        json={"name": "Still", "description": "Image template", "category": "image"},
    ).json()

    client.post(
        "/credit_packs/",
        json={"user_id": user["id"], "pack_name": "40 credits", "credits": 40, "price": 9.99},
    )
    client.post(
        "/credit_packs/",
        json={"user_id": user["id"], "pack_name": "10 credits", "credits": 10, "price": 4.99},
    )

    client.post(
        "/generations/",
        json={
            "user_id": user["id"],
            "template_id": template["id"],
            "input_path": "/tmp/a.png",
            "status": "completed",
            "credits_used": 7,
        },
    )
    client.post(
        "/generations/",
        json={
            "user_id": user["id"],
            "template_id": template["id"],
            "input_path": "/tmp/b.png",
            "status": "pending",
            "credits_used": 2,
        },
    )

    response = client.get("/admin/reports/credits")
    assert response.status_code == 200
    data = response.json()

    assert data["issued_credits"] == 50
    assert data["refunded_credits"] == 0
    assert data["chargeback_credits"] == 0
    assert data["net_issued_credits"] == 50
    assert data["purchased_credit_packs"] == 2
    assert data["generation_count"] == 2
    assert data["consumed_credits"] == 9
    assert data["remaining_credits"] == 41
    assert data["users"][0]["issued_credits"] == 50
    assert data["users"][0]["refunded_credits"] == 0
    assert data["users"][0]["chargeback_credits"] == 0
    assert data["users"][0]["net_issued_credits"] == 50
    assert data["users"][0]["consumed_credits"] == 9
    assert data["users"][0]["remaining_credits"] == 41
