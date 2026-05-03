import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_template_sync_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class TemplateAdminSyncTests(unittest.TestCase):
    def setUp(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_template_admin_sync.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{self.test_db_path}"
        importlib.reload(db_module)
        importlib.reload(models_module)
        importlib.reload(schemas_module)
        importlib.reload(crud_module)
        importlib.reload(main_module)
        db_module.Base.metadata.create_all(bind=db_module.engine)
        self.client = TestClient(main_module.app)

    def tearDown(self):
        self.client.close()
        close_all_sessions()
        db_module.engine.dispose()
        self.tmpdir.cleanup()

    def test_template_create_update_and_public_visibility_include_admin_fields(self):
        create_response = self.client.post(
            "/admin/templates/",
            json={
                "name": "Cinematic Hug",
                "description": "Hero template",
                "category": "Main",
                "is_spicy": True,
                "credit_cost": 20,
                "disclaimer_text": "Use a clear portrait image.",
                "best_use_text": "Good lighting helps.",
                "generation_type": "image_to_video",
                "comfyui_server_id": "primary-server",
                "workflow_key": "hug_video_flux_v3",
                "input_node_mapping": "input_image",
                "output_node_mapping": "output_video",
                "primary_color": "#FFAA00",
                "secondary_color": "#AA5500",
                "accent_color": "#FF0066",
                "background_color": "#120D0B",
                "card_color": "#3B2D22",
                "text_color": "#FFF8F1",
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        created = create_response.json()
        self.assertEqual(created["credit_cost"], 20)
        self.assertTrue(created["is_spicy"])
        self.assertEqual(created["workflow_key"], "hug_video_flux_v3")
        self.assertEqual(created["comfyui_server_id"], "primary-server")
        self.assertEqual(created["input_node_mapping"], "input_image")
        self.assertEqual(created["output_node_mapping"], "output_video")
        self.assertEqual(created["primary_color"], "#FFAA00")
        self.assertEqual(created["background_color"], "#120D0B")

        public_get = self.client.get(f"/templates/{created['id']}")
        self.assertEqual(public_get.status_code, 200, public_get.text)
        self.assertEqual(public_get.json()["generation_type"], "image_to_video")
        self.assertTrue(public_get.json()["is_spicy"])
        self.assertEqual(public_get.json()["card_color"], "#3B2D22")

        update_response = self.client.put(
            f"/admin/templates/{created['id']}",
            json={
                "is_active": False,
                "is_spicy": False,
                "credit_cost": 25,
                "workflow_key": "hug_video_flux_v4",
                "comfyui_server_id": "backup-server",
                "primary_color": "#00AACC",
                "text_color": "#FFFFFF",
            },
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        updated = update_response.json()
        self.assertFalse(updated["is_active"])
        self.assertFalse(updated["is_spicy"])
        self.assertEqual(updated["credit_cost"], 25)
        self.assertEqual(updated["workflow_key"], "hug_video_flux_v4")
        self.assertEqual(updated["comfyui_server_id"], "backup-server")
        self.assertEqual(updated["primary_color"], "#00AACC")
        self.assertEqual(updated["text_color"], "#FFFFFF")

        hidden_public_get = self.client.get(f"/templates/{created['id']}")
        self.assertEqual(hidden_public_get.status_code, 404, hidden_public_get.text)

    def test_template_preview_upload_session_attaches_preview_file_and_serves_download_url(self):
        create_response = self.client.post(
            "/admin/templates/",
            json={"name": "Previewable", "description": "desc", "category": "Main"},
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        template = create_response.json()

        session_response = self.client.post(
            f"/admin/templates/{template['id']}/preview-upload-session",
            json={"filename": "template-preview.png", "mime_type": "image/png"},
        )
        self.assertEqual(session_response.status_code, 201, session_response.text)
        payload = session_response.json()
        self.assertEqual(payload["file"]["kind"], "template_preview")

        upload_response = self.client.put(
            payload["upload"]["url"],
            content=b"fake-preview-bytes",
            headers={"content-type": "image/png"},
        )
        self.assertEqual(upload_response.status_code, 201, upload_response.text)

        admin_get = self.client.get(f"/admin/templates/{template['id']}")
        self.assertEqual(admin_get.status_code, 200, admin_get.text)
        admin_body = admin_get.json()
        self.assertEqual(admin_body["preview_image_file_id"], payload["file"]["id"])
        self.assertIsNotNone(admin_body["preview_image_file"])
        self.assertEqual(admin_body["preview_image_file"]["size_bytes"], len(b"fake-preview-bytes"))

        preview_url_response = self.client.get(f"/templates/{template['id']}/preview-url")
        self.assertEqual(preview_url_response.status_code, 200, preview_url_response.text)
        download_response = self.client.get(preview_url_response.json()["url"])
        self.assertEqual(download_response.status_code, 200, download_response.text)
        self.assertEqual(download_response.content, b"fake-preview-bytes")

        preview_public_url_response = self.client.get(f"/templates/{template['id']}/preview-public-url")
        self.assertEqual(preview_public_url_response.status_code, 200, preview_public_url_response.text)
        public_download_response = self.client.get(preview_public_url_response.json()["url"])
        self.assertEqual(public_download_response.status_code, 200, public_download_response.text)
        self.assertEqual(public_download_response.content, b"fake-preview-bytes")


if __name__ == "__main__":
    unittest.main()
