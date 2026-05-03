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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_credit_purchase_verify_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class TestCreditPurchaseVerify:
    def setup_method(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_credit_purchase_verify.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{self.test_db_path}"
        importlib.reload(db_module)
        importlib.reload(models_module)
        importlib.reload(schemas_module)
        importlib.reload(crud_module)
        importlib.reload(main_module)
        db_module.Base.metadata.create_all(bind=db_module.engine)
        self.client = TestClient(main_module.app)

    def teardown_method(self):
        self.client.close()
        close_all_sessions()
        db_module.engine.dispose()
        self.tmpdir.cleanup()

    def create_user(self, email: str = "verify@example.com"):
        response = self.client.post("/users/", json={"email": email})
        assert response.status_code == 201, response.text
        return response.json()

    def test_verify_purchase_grants_credits_and_is_idempotent(self, monkeypatch):
        user = self.create_user()
        patch_response = self.client.patch(
            "/admin/credit-pack-configs/3",
            json={
                "product_key": "credit_pack_3",
                "store_product_key_ios": "credits_300_ios",
                "store_product_key_android": "credits_300_android",
                "active": True,
            },
        )
        assert patch_response.status_code == 200, patch_response.text

        def fake_verify_purchase(receipt_data: str, app_user_id: str):
            assert receipt_data == "receipt-token-1"
            assert app_user_id == str(user["id"])
            return {
                "customer_info": {
                    "non_subscriptions": {
                        "credits_300_ios": [
                            {"transaction_id": "txn_300_1"}
                        ]
                    }
                }
            }

        monkeypatch.setattr(main_module, "verify_purchase", fake_verify_purchase)

        payload = {
            "user_id": user["id"],
            "platform": "ios",
            "product_id": "credits_300_ios",
            "receipt_data": "receipt-token-1",
        }

        first = self.client.post("/credits/purchase/verify", json=payload)
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["status"] == "credited"
        assert first_body["credited"] is True
        assert first_body["credits_granted"] == 300
        assert first_body["transaction_id"] == "txn_300_1"
        assert first_body["remaining_credits"] == 300

        duplicate = self.client.post("/credits/purchase/verify", json=payload)
        assert duplicate.status_code == 200, duplicate.text
        duplicate_body = duplicate.json()
        assert duplicate_body["status"] == "duplicate"
        assert duplicate_body["credited"] is False
        assert duplicate_body["remaining_credits"] == 300

        credit_history = self.client.get("/credit_packs/", params={"user_id": user["id"]})
        assert credit_history.status_code == 200, credit_history.text
        items = credit_history.json()
        assert len(items) == 1
        assert items[0]["provider"] == "RevenueCat"
        assert items[0]["product_key"] == "credits_300_ios"
        assert items[0]["external_transaction_id"] == "txn_300_1"

    def test_verify_purchase_rejects_unknown_product_mapping(self, monkeypatch):
        user = self.create_user("unknown-product@example.com")
        monkeypatch.setattr(main_module, "verify_purchase", lambda *_args, **_kwargs: {"customer_info": {}})
        response = self.client.post(
            "/credits/purchase/verify",
            json={
                "user_id": user["id"],
                "platform": "android",
                "product_id": "missing.sku",
                "receipt_data": "receipt-token-2",
            },
        )
        assert response.status_code == 422
        assert "No active credit pack config matched" in response.json()["detail"]
