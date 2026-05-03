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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_admin_credit_pack_configs_initial.db"
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
    test_db_path = Path(tmpdir.name) / "test_admin_credit_pack_configs.db"
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


def test_credit_pack_config_list_seeds_five_slots_and_public_endpoint_matches():
    admin_response = client.get("/admin/credit-pack-configs")
    public_response = client.get("/credits/packs")

    assert admin_response.status_code == 200
    assert public_response.status_code == 200

    admin_payload = admin_response.json()
    public_payload = public_response.json()

    assert len(admin_payload) == 5
    assert [row["slot_number"] for row in admin_payload] == [1, 2, 3, 4, 5]
    assert admin_payload == public_payload
    assert admin_payload[0]["credit_amount"] == 50
    assert admin_payload[0]["display_price_text"] == "€4.99"


def test_credit_pack_config_patch_updates_expected_fields():
    response = client.patch(
        "/admin/credit-pack-configs/3",
        json={
            "credit_amount": 333,
            "price": 24.5,
            "display_price_text": "€24.50",
            "product_key": "pack_333",
            "store_product_key_android": "android.pack.333",
            "store_product_key_ios": "ios.pack.333",
            "active": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["slot_number"] == 3
    assert payload["credit_amount"] == 333
    assert payload["price"] == 24.5
    assert payload["display_price_text"] == "€24.50"
    assert payload["product_key"] == "pack_333"
    assert payload["store_product_key_android"] == "android.pack.333"
    assert payload["store_product_key_ios"] == "ios.pack.333"


def test_credit_pack_config_delete_resets_slot_instead_of_removing_it():
    client.patch(
        "/admin/credit-pack-configs/2",
        json={
            "credit_amount": 222,
            "display_price_text": "€22.20",
            "store_product_key_android": "android.two",
        },
    )

    response = client.delete("/admin/credit-pack-configs/2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["slot_number"] == 2
    assert payload["credit_amount"] == 120
    assert payload["display_price_text"] == "€10.99"
    assert payload["product_key"] == "credit_pack_2"
    assert payload["store_product_key_android"] is None
    assert payload["store_product_key_ios"] is None
    assert payload["active"] is False

    follow_up = client.get("/admin/credit-pack-configs")
    assert len(follow_up.json()) == 5


def test_credit_pack_config_post_is_rejected_once_all_five_slots_exist():
    client.get("/admin/credit-pack-configs")

    response = client.post(
        "/admin/credit-pack-configs",
        json={
            "slot_number": 5,
            "credit_amount": 999,
            "price": 99.0,
            "display_price_text": "€99.00",
            "product_key": "duplicate.slot",
            "active": True,
        },
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]
