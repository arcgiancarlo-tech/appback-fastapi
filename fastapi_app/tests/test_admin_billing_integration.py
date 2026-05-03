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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_admin_billing_initial.db"
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
    test_db_path = Path(tmpdir.name) / "test_admin_billing.db"
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


def test_admin_billing_integration_defaults_are_bootstrapped():
    response = client.get("/admin/billing-integration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "RevenueCat"
    assert payload["environment"] == "test"
    assert payload["connection_status"] == "disconnected"
    assert payload["public_api_key"] == ""
    assert payload["secret_key"] == ""
    assert payload["project_id"] == ""
    assert payload["notes"] == ""



def test_admin_billing_integration_and_pack_store_mapping_can_be_saved():
    billing_response = client.put(
        "/admin/billing-integration",
        json={
            "provider": "RevenueCat",
            "environment": "live",
            "connection_status": "connected",
            "public_api_key": "public_live_123",
            "secret_key": "secret_live_456",
            "project_id": "spinai-mobile",
            "notes": "Primary mobile billing config",
        },
    )
    assert billing_response.status_code == 200
    assert billing_response.json()["project_id"] == "spinai-mobile"

    pack_response = client.patch(
        "/admin/credit-pack-configs/3",
        json={
            "store_product_key_ios": "credits_300_ios",
            "store_product_key_android": "credits_300_android",
        },
    )

    assert pack_response.status_code == 200
    assert pack_response.json()["store_product_key_ios"] == "credits_300_ios"
    assert pack_response.json()["store_product_key_android"] == "credits_300_android"

    persisted_billing = client.get("/admin/billing-integration")
    persisted_packs = client.get("/admin/credit-pack-configs")

    assert persisted_billing.status_code == 200
    assert persisted_billing.json()["provider"] == "RevenueCat"
    assert persisted_billing.json()["environment"] == "live"
    assert persisted_billing.json()["connection_status"] == "connected"
    assert persisted_billing.json()["public_api_key"] == "public_live_123"
    assert persisted_billing.json()["secret_key"] == "secret_live_456"
    assert persisted_billing.json()["project_id"] == "spinai-mobile"

    pack_3 = next(item for item in persisted_packs.json() if item["slot_number"] == 3)
    assert pack_3["store_product_key_ios"] == "credits_300_ios"
    assert pack_3["store_product_key_android"] == "credits_300_android"
