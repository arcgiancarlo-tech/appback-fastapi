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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_revenuecat_initial_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"
os.environ["REVENUECAT_PRODUCT_CREDITS"] = '{"pack_100": 100, "pack_50": 50}'
os.environ["REVENUECAT_WEBHOOK_SECRET"] = "test-secret"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class TestRevenueCatWebhooks:
    def setup_method(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_revenuecat_webhooks.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{self.test_db_path}"
        os.environ["REVENUECAT_PRODUCT_CREDITS"] = '{"pack_100": 100, "pack_50": 50}'
        os.environ["REVENUECAT_WEBHOOK_SECRET"] = "test-secret"
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

    def create_user(self, email: str):
        response = self.client.post("/users/", json={"email": email})
        assert response.status_code == 201, response.text
        return response.json()

    def create_template(self, name: str = "Template"):
        response = self.client.post(
            "/templates/",
            json={"name": name, "description": "desc", "category": "general"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def create_credit_pack(self, user_id: int, credits: int, price: float, name: str = "Pack"):
        response = self.client.post(
            "/credit_packs/",
            json={"user_id": user_id, "pack_name": name, "credits": credits, "price": price},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def create_generation(self, user_id: int, template_id: int, credits_used: int):
        response = self.client.post(
            "/generations/",
            json={
                "user_id": user_id,
                "template_id": template_id,
                "input_path": "/tmp/in.png",
                "output_path": "/tmp/out.png",
                "status": "completed",
                "credits_used": credits_used,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def post_webhook(self, event: dict, secret: str = "test-secret"):
        return self.client.post(
            "/webhooks/revenuecat",
            json={"event": event},
            headers={"Authorization": f"Bearer {secret}"},
        )

    def test_revenuecat_refund_webhook_is_idempotent_and_updates_reports(self):
        user = self.create_user("payer@example.com")
        template = self.create_template()
        self.create_credit_pack(user["id"], credits=100, price=29.99, name="100 credits")
        self.create_generation(user["id"], template["id"], credits_used=25)

        refund_event = {
            "id": "evt_refund_1",
            "type": "REFUND",
            "app_user_id": str(user["id"]),
            "product_id": "pack_100",
            "transaction_id": "txn_1",
            "original_transaction_id": "orig_txn_1",
            "price_in_purchased_currency": 29.99,
            "currency": "USD",
            "event_timestamp_ms": 1714500000000,
            "environment": "SANDBOX",
        }

        first = self.post_webhook(refund_event)
        assert first.status_code == 200, first.text
        assert first.json() == {
            "status": "processed",
            "event_id": "evt_refund_1",
            "processed": True,
            "refund_kind": "refund",
            "user_id": user["id"],
            "credits_revoked": 100,
        }

        duplicate = self.post_webhook(refund_event)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["status"] == "duplicate"
        assert duplicate.json()["processed"] is False

        refund_report = self.client.get("/admin/reports/revenuecat/refunds")
        assert refund_report.status_code == 200, refund_report.text
        refund_data = refund_report.json()
        assert refund_data["total_events"] == 1
        assert refund_data["refund_event_count"] == 1
        assert refund_data["chargeback_event_count"] == 0
        assert refund_data["refunded_credits"] == 100
        assert refund_data["chargeback_credits"] == 0
        assert refund_data["refunded_amount"] == 29.99
        assert refund_data["events"][0]["event_id"] == "evt_refund_1"

        credit_report = self.client.get("/admin/reports/credits")
        assert credit_report.status_code == 200, credit_report.text
        credit_data = credit_report.json()
        assert credit_data["issued_credits"] == 100
        assert credit_data["refunded_credits"] == 100
        assert credit_data["chargeback_credits"] == 0
        assert credit_data["net_issued_credits"] == 0
        assert credit_data["purchased_amount"] == 29.99
        assert credit_data["refunded_amount"] == 29.99
        assert credit_data["chargeback_amount"] == 0
        assert credit_data["net_purchase_amount"] == 0.0
        assert credit_data["remaining_credits"] == -25
        assert credit_data["users"][0]["refund_event_count"] == 1
        assert credit_data["users"][0]["remaining_credits"] == -25

        usage_summary = self.client.get("/admin/reports/usage-summary")
        assert usage_summary.status_code == 200, usage_summary.text
        usage_data = usage_summary.json()
        assert usage_data["credits_earned"] == 100
        assert usage_data["credits_refunded"] == 100
        assert usage_data["credits_refunded_chargebacks"] == 0
        assert usage_data["credits_balance"] == -25

    def test_revenuecat_chargeback_cancellation_is_classified_and_filtered(self):
        user = self.create_user("chargeback@example.com")
        self.create_credit_pack(user["id"], credits=50, price=12.0, name="50 credits")

        response = self.post_webhook(
            {
                "id": "evt_chargeback_1",
                "type": "CANCELLATION",
                "cancel_reason": "CHARGEBACK",
                "app_user_id": "chargeback@example.com",
                "product_id": "pack_50",
                "amount": 12.0,
                "currency": "USD",
                "event_timestamp": "2026-05-01T00:00:00Z",
                "environment": "PRODUCTION",
            }
        )
        assert response.status_code == 200, response.text
        assert response.json()["refund_kind"] == "chargeback"
        assert response.json()["credits_revoked"] == 50

        report = self.client.get(f"/admin/reports/revenuecat/refunds?user_id={user['id']}")
        assert report.status_code == 200, report.text
        data = report.json()
        assert data["total_events"] == 1
        assert data["refund_event_count"] == 0
        assert data["chargeback_event_count"] == 1
        assert data["chargeback_credits"] == 50
        assert data["chargeback_amount"] == 12.0

        credit_report = self.client.get(f"/admin/reports/credits?user_id={user['id']}")
        assert credit_report.status_code == 200, credit_report.text
        body = credit_report.json()
        assert body["chargeback_credits"] == 50
        assert body["refunded_credits"] == 0
        assert body["net_issued_credits"] == 0
        assert body["chargeback_event_count"] == 1

    def test_revenuecat_webhook_rejects_invalid_secret_and_unknown_user(self):
        user = self.create_user("known@example.com")
        assert user["id"] > 0

        invalid_secret = self.post_webhook(
            {
                "id": "evt_invalid_secret",
                "type": "REFUND",
                "app_user_id": str(user["id"]),
            },
            secret="wrong-secret",
        )
        assert invalid_secret.status_code == 401

        unknown_user = self.post_webhook(
            {
                "id": "evt_missing_user",
                "type": "REFUND",
                "app_user_id": "999999",
            }
        )
        assert unknown_user.status_code == 422
        assert "No user matched" in unknown_user.json()["detail"]

    def test_non_refund_events_are_ignored(self):
        user = self.create_user("ignore@example.com")
        response = self.post_webhook(
            {
                "id": "evt_purchase_1",
                "type": "INITIAL_PURCHASE",
                "app_user_id": str(user["id"]),
                "product_id": "pack_100",
            }
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "status": "ignored",
            "event_id": "evt_purchase_1",
            "processed": False,
            "refund_kind": None,
            "user_id": None,
            "credits_revoked": 0,
        }
