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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_transactional_email_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"
os.environ["TRANSACTIONAL_EMAIL_SHARED_SECRET"] = "test-shared-secret"
os.environ["TRANSACTIONAL_EMAIL_PROVIDER"] = "stub"
os.environ["TRANSACTIONAL_EMAIL_STUB_MODE"] = "true"
os.environ["TRANSACTIONAL_EMAIL_FROM_EMAIL"] = "noreply@example.com"
os.environ["APP_BASE_URL"] = "https://app.spinaistudio.test"
os.environ["INVITE_BASE_URL"] = "https://invite.spinaistudio.test"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import transactional_email as transactional_email_module  # noqa: E402


class TestTransactionalEmailHooks:
    def setup_method(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_transactional_email.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{self.test_db_path}"
        os.environ["TRANSACTIONAL_EMAIL_SHARED_SECRET"] = "test-shared-secret"
        os.environ["TRANSACTIONAL_EMAIL_PROVIDER"] = "stub"
        os.environ["TRANSACTIONAL_EMAIL_STUB_MODE"] = "true"
        os.environ["TRANSACTIONAL_EMAIL_FROM_EMAIL"] = "noreply@example.com"
        os.environ["APP_BASE_URL"] = "https://app.spinaistudio.test"
        os.environ["INVITE_BASE_URL"] = "https://invite.spinaistudio.test"
        os.environ.pop("TRANSACTIONAL_EMAIL_PROVIDER_API_KEY", None)
        importlib.reload(db_module)
        importlib.reload(models_module)
        importlib.reload(crud_module)
        importlib.reload(transactional_email_module)
        importlib.reload(main_module)
        db_module.Base.metadata.create_all(bind=db_module.engine)
        self.client = TestClient(main_module.app)

    def teardown_method(self):
        self.client.close()
        close_all_sessions()
        db_module.engine.dispose()
        self.tmpdir.cleanup()

    def test_health_requires_shared_secret(self):
        response = self.client.get("/internal/transactional-email/health")

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid transactional email secret"

    def test_health_reports_stub_mode(self):
        response = self.client.get(
            "/internal/transactional-email/health",
            headers={"X-Transactional-Email-Secret": "test-shared-secret"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "mode": "stub",
            "provider": "stub",
            "missing_credentials": [],
        }

    def test_reset_hook_returns_stubbed_preview_and_link(self):
        response = self.client.post(
            "/internal/transactional-email/reset",
            headers={"X-Transactional-Email-Secret": "test-shared-secret"},
            json={"email": "user@example.com", "reset_token": "reset-token-12345"},
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["accepted"] is True
        assert body["template"] == "password_reset"
        assert body["delivery_stubbed"] is True
        assert body["generated_links"]["reset_link"].startswith("https://app.spinaistudio.test/reset-password?")
        assert "token=reset-token-12345" in body["generated_links"]["reset_link"]
        assert body["missing_credentials"] == []

    def test_invite_hook_uses_invite_base_url(self):
        response = self.client.post(
            "/internal/transactional-email/invite",
            headers={"X-Transactional-Email-Secret": "test-shared-secret"},
            json={
                "email": "invitee@example.com",
                "invite_token": "invite-token-12345",
                "invited_by_email": "admin@example.com",
            },
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["template"] == "invite"
        assert body["generated_links"]["invite_link"].startswith("https://invite.spinaistudio.test/accept-invite?")
        assert "admin@example.com" in body["preview_text"]

    def test_notify_hook_surfaces_missing_provider_key_when_stub_disabled(self):
        os.environ["TRANSACTIONAL_EMAIL_PROVIDER"] = "resend"
        os.environ["TRANSACTIONAL_EMAIL_STUB_MODE"] = "false"
        importlib.reload(transactional_email_module)
        importlib.reload(main_module)
        self.client.close()
        self.client = TestClient(main_module.app)

        response = self.client.post(
            "/internal/transactional-email/notify",
            headers={"X-Transactional-Email-Secret": "test-shared-secret"},
            json={
                "email": "user@example.com",
                "subject": "Generation complete",
                "message_text": "Your asset is ready.",
                "notification_type": "generation_complete",
                "action_url": "https://app.spinaistudio.test/jobs/42",
                "action_label": "View job",
            },
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["mode"] == "live_configured"
        assert body["delivery_stubbed"] is False
        assert body["missing_credentials"] == ["TRANSACTIONAL_EMAIL_PROVIDER_API_KEY"]
        assert body["generated_links"]["action_url"] == "https://app.spinaistudio.test/jobs/42"
