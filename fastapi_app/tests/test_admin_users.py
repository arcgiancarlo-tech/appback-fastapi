import importlib
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_admin_users_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402


client = None
tmpdir = None


def setup_function():
    global client, tmpdir
    db_module.engine.dispose()
    tmpdir = tempfile.TemporaryDirectory()
    test_db_path = Path(tmpdir.name) / "test_admin_users.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"
    importlib.reload(db_module)
    importlib.reload(models_module)
    importlib.reload(crud_module)
    importlib.reload(main_module)
    db_module.Base.metadata.create_all(bind=db_module.engine)
    client = TestClient(main_module.app)


def teardown_function():
    global client, tmpdir
    if client is not None:
        client.close()
        client = None
    close_all_sessions()
    db_module.engine.dispose()
    if tmpdir is not None:
        tmpdir.cleanup()
        tmpdir = None


def seed_users():
    users = [
        client.post("/users/", json={"email": "alpha@example.com"}).json(),
        client.post("/users/", json={"email": "beta@example.com"}).json(),
        client.post("/users/", json={"email": "gamma@example.com"}).json(),
    ]
    with db_module.SessionLocal() as db:
        from fastapi_app.models import User

        beta = db.query(User).filter(User.email == "beta@example.com").first()
        beta.is_active = False
        db.commit()

    template = client.post(
        "/templates/",
        json={"name": "Starter", "description": "desc", "category": "basic"},
    ).json()
    client.post(
        "/generations/",
        json={
            "user_id": users[0]["id"],
            "template_id": template["id"],
            "input_path": "input-a.png",
            "status": "completed",
        },
    )
    client.post(
        "/credit_packs/",
        json={"user_id": users[0]["id"], "pack_name": "50 credits", "credits": 50, "price": 9.99},
    )
    client.post(
        "/credit_packs/",
        json={"user_id": users[2]["id"], "pack_name": "100 credits", "credits": 100, "price": 19.99},
    )
    return users


def test_admin_user_list_supports_filters_and_summary_fields():
    seed_users()

    response = client.get("/admin/users/", params={"is_active": True, "search": "alpha"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["email"] == "alpha@example.com"
    assert payload[0]["is_active"] is True
    assert payload[0]["status"] == "active"
    assert payload[0]["signup_method"] == "email"
    assert payload[0]["total_credits"] == 50
    assert payload[0]["remaining_credits"] == 50
    assert payload[0]["total_generations"] == 1
    assert payload[0]["completed_generations"] == 1


def test_admin_user_detail_returns_rollups_and_404_for_missing():
    users = seed_users()

    response = client.get(f"/admin/users/{users[1]['id']}")
    missing_response = client.get("/admin/users/9999")

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "beta@example.com"
    assert payload["is_active"] is False
    assert payload["status"] == "suspended"
    assert payload["total_credits"] == 0
    assert payload["manual_credit_actions"] == []
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "User not found"


def test_admin_user_count_uses_filters():
    seed_users()

    response = client.get("/admin/users/count", params={"is_active": True, "search": "example.com"})

    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_admin_user_moderation_and_manual_credit_actions():
    users = seed_users()

    suspend = client.post(f"/admin/users/{users[0]['id']}/suspend", json={"reason": "abuse"})
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "suspended"
    assert suspend.json()["is_active"] is False

    reactivate = client.post(f"/admin/users/{users[0]['id']}/reactivate", json={"reason": "resolved"})
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "active"
    assert reactivate.json()["is_active"] is True

    credit_action = client.post(
        f"/admin/users/{users[0]['id']}/credit-actions",
        json={"credits": 15, "reason": "support", "note": "goodwill"},
    )
    assert credit_action.status_code == 201
    assert credit_action.json()["credits"] == 15
    assert credit_action.json()["reason"] == "support"
    assert credit_action.json()["note"] == "goodwill"

    detail = client.get(f"/admin/users/{users[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["total_credits"] == 65
    assert detail.json()["remaining_credits"] == 65
    assert len(detail.json()["manual_credit_actions"]) == 1
    assert detail.json()["manual_credit_actions"][0]["credits"] == 15


def test_admin_user_state_summary_reports_rollup_counts():
    seed_users()

    response = client.get("/admin/users/state-summary")

    assert response.status_code == 200
    assert response.json() == {
        "total_users": 3,
        "active_users": 2,
        "inactive_users": 1,
        "users_with_generations": 1,
        "users_with_credit_packs": 2,
    }
