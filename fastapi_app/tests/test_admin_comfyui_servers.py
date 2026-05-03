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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_admin_comfyui_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class TestAdminComfyUIServers:
    def setup_method(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_admin_comfyui_servers.db"
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

    def test_admin_comfyui_server_crud_and_status_mapping(self):
        created = self.client.post(
            "/admin/comfyui/servers",
            json={
                "name": "Primary GPU",
                "base_url": "https://comfy-a.example.com",
                "auth_token": "secret-token",
                "notes": "fastest GPU",
                "is_active": True,
                "healthcheck_status": "healthy",
                "healthcheck_message": "ready",
                "last_checked_at": "2026-05-01T05:30:00Z"
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["name"] == "Primary GPU"
        assert body["base_url"] == "https://comfy-a.example.com"
        assert body["auth_token"] == "secret-token"
        assert body["notes"] == "fastest GPU"
        assert body["status"] == "Online"
        assert body["healthcheck_status"] == "healthy"

        server_id = body["id"]

        updated = self.client.put(
            f"/admin/comfyui/servers/{server_id}",
            json={
                "notes": "image-only testing box",
                "healthcheck_status": "checking",
                "healthcheck_message": "ping in progress"
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["notes"] == "image-only testing box"
        assert updated.json()["status"] == "Testing"

        detail = self.client.get(f"/admin/comfyui/servers/{server_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "Testing"

        disabled = self.client.put(
            f"/admin/comfyui/servers/{server_id}",
            json={"is_active": False, "healthcheck_status": "healthy"},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["status"] == "Disabled"

        deleted = self.client.delete(f"/admin/comfyui/servers/{server_id}")
        assert deleted.status_code == 204, deleted.text

        missing = self.client.get(f"/admin/comfyui/servers/{server_id}")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "ComfyUI server not found"

    def test_admin_comfyui_server_list_filters_support_ui_statuses(self):
        payloads = [
            {
                "name": "Online Box",
                "base_url": "https://online.example.com",
                "is_active": True,
                "healthcheck_status": "ok",
            },
            {
                "name": "Offline Box",
                "base_url": "https://offline.example.com",
                "is_active": True,
                "healthcheck_status": "unreachable",
                "notes": "network issue",
            },
            {
                "name": "Broken Auth Box",
                "base_url": "https://error.example.com",
                "is_active": True,
                "healthcheck_status": "invalid_auth",
            },
            {
                "name": "Disabled Box",
                "base_url": "https://disabled.example.com",
                "is_active": False,
                "healthcheck_status": "healthy",
            },
        ]
        for payload in payloads:
            response = self.client.post("/admin/comfyui/servers", json=payload)
            assert response.status_code == 201, response.text

        listed = self.client.get("/admin/comfyui/servers")
        assert listed.status_code == 200, listed.text
        statuses = {row["name"]: row["status"] for row in listed.json()}
        assert statuses == {
            "Online Box": "Online",
            "Offline Box": "Offline",
            "Broken Auth Box": "Connection Error",
            "Disabled Box": "Disabled",
        }

        online_only = self.client.get("/admin/comfyui/servers", params={"status": "Online"})
        assert online_only.status_code == 200, online_only.text
        assert [row["name"] for row in online_only.json()] == ["Online Box"]

        active_only = self.client.get("/admin/comfyui/servers", params={"include_inactive": False})
        assert active_only.status_code == 200, active_only.text
        assert {row["name"] for row in active_only.json()} == {"Online Box", "Offline Box", "Broken Auth Box"}

        dashboard = self.client.get("/dashboard/admin/comfyui/servers", params={"status": "Connection Error"})
        assert dashboard.status_code == 200, dashboard.text
        assert [row["name"] for row in dashboard.json()] == ["Broken Auth Box"]
