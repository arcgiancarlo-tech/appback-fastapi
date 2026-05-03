import base64
import importlib
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_generation_file_flow.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"
os.environ["COMFYUI_CALLBACK_SECRET"] = "comfy-secret"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class TestGenerationFileFlow:
    def setup_method(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_generation_file_flow.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{self.test_db_path}"
        os.environ["COMFYUI_CALLBACK_SECRET"] = "comfy-secret"
        importlib.reload(db_module)
        importlib.reload(models_module)
        importlib.reload(schemas_module)
        importlib.reload(crud_module)
        importlib.reload(main_module)
        db_module.Base.metadata.create_all(bind=db_module.engine)
        self.client = TestClient(main_module.app)

    def auth_headers(self):
        return {"Authorization": "Bearer comfy-secret"}

    def teardown_method(self):
        self.client.close()
        close_all_sessions()
        db_module.engine.dispose()
        self.tmpdir.cleanup()

    def test_upload_and_generation_result_flow_links_job_and_files(self):
        user = self.client.post("/users/", json={"email": "flow@example.com"}).json()
        template = self.client.post(
            "/templates/",
            json={"name": "Flow Template", "description": "desc", "category": "video"},
        ).json()

        upload_bytes = b"fake-input-image"
        upload = self.client.post(
            "/uploads/",
            json={
                "user_id": user["id"],
                "filename": "input.png",
                "mime_type": "image/png",
                "content_base64": base64.b64encode(upload_bytes).decode("ascii"),
            },
        )
        assert upload.status_code == 201, upload.text
        upload_file = upload.json()
        assert upload_file["kind"] == "user_input"
        assert upload_file["owner_user_id"] == user["id"]

        generation = self.client.post(
            "/generations/",
            json={
                "user_id": user["id"],
                "template_id": template["id"],
                "input_path": upload_file["relative_path"],
                "input_file_id": upload_file["id"],
                "status": "uploaded",
                "workflow_key": "hug_video_flux_v3",
                "comfyui_server_id": "primary-server",
                "result_kind": "video",
            },
        )
        assert generation.status_code == 201, generation.text
        generation_body = generation.json()
        assert generation_body["input_file_id"] == upload_file["id"]
        assert generation_body["status"] == "uploaded"

        status_update = self.client.post(
            f"/generations/{generation_body['id']}/status",
            json={
                "status": "running",
                "comfyui_job_id": "comfy-job-123",
                "started_at": "2026-05-01T03:00:00Z",
            },
            headers=self.auth_headers(),
        )
        assert status_update.status_code == 200, status_update.text
        assert status_update.json()["comfyui_job_id"] == "comfy-job-123"
        assert status_update.json()["status"] == "running"

        result_bytes = b"fake-output-video"
        result = self.client.post(
            f"/generations/{generation_body['id']}/result",
            json={
                "filename": "output.mp4",
                "mime_type": "video/mp4",
                "content_base64": base64.b64encode(result_bytes).decode("ascii"),
                "comfyui_job_id": "comfy-job-123",
                "comfyui_server_id": "primary-server",
                "workflow_key": "hug_video_flux_v3",
                "result_kind": "video",
            },
            headers=self.auth_headers(),
        )
        assert result.status_code == 200, result.text
        result_body = result.json()
        assert result_body["status"] == "completed"
        assert result_body["output_file_id"] is not None
        assert result_body["output_path"].endswith("output.mp4")
        assert result_body["input_file"]["id"] == upload_file["id"]
        assert result_body["output_file"]["kind"] == "generation_output"

        job_detail = self.client.get(f"/generations/{generation_body['id']}", params={"user_id": user["id"]})
        assert job_detail.status_code == 200, job_detail.text
        assert job_detail.json()["output_file"]["owner_user_id"] == user["id"]

        result_url = self.client.get(
            f"/generations/{generation_body['id']}/result-url",
            params={"user_id": user["id"]},
        )
        assert result_url.status_code == 200, result_url.text
        signed_download_path = urlparse(result_url.json()["url"]).path
        download = self.client.get(signed_download_path)
        assert download.status_code == 200, download.text
        assert download.content == result_bytes
        assert download.headers["content-type"].startswith("video/mp4")

        public_result_url = self.client.get(
            f"/generations/{generation_body['id']}/result-public-url",
            params={"user_id": user["id"]},
        )
        assert public_result_url.status_code == 200, public_result_url.text
        public_result_path = urlparse(public_result_url.json()["url"]).path
        public_result = self.client.get(public_result_path)
        assert public_result.status_code == 200, public_result.text
        assert public_result.content == result_bytes

        admin_jobs = self.client.get("/admin/jobs/", params={"user_id": user["id"]})
        assert admin_jobs.status_code == 200, admin_jobs.text
        job_report = admin_jobs.json()[0]
        assert job_report["input_file_id"] == upload_file["id"]
        assert job_report["output_file_id"] == result_body["output_file_id"]
        assert job_report["comfyui_job_id"] == "comfy-job-123"
        assert job_report["workflow_key"] == "hug_video_flux_v3"

    def test_signed_upload_session_supports_large_binary_put_and_download(self):
        user = self.client.post("/users/", json={"email": "signed-upload@example.com"}).json()

        session_response = self.client.post(
            "/files/upload-sessions",
            json={
                "owner_user_id": user["id"],
                "filename": "big-video.mp4",
                "mime_type": "video/mp4",
                "kind": "user_input",
                "max_bytes": 5_000_000,
            },
        )
        assert session_response.status_code == 201, session_response.text
        session_body = session_response.json()
        file_id = session_body["file"]["id"]

        payload = b"0123456789" * 10000
        upload_path = urlparse(session_body["upload"]["url"]).path
        upload = self.client.put(upload_path, content=payload, headers={"content-type": "video/mp4"})
        assert upload.status_code == 201, upload.text
        assert upload.json()["size_bytes"] == len(payload)

        file_detail = self.client.get(f"/files/{file_id}")
        assert file_detail.status_code == 200, file_detail.text
        assert file_detail.json()["size_bytes"] == len(payload)
        assert file_detail.json()["original_filename"] == "big-video.mp4"

        download_url = self.client.get(f"/files/{file_id}/download-url", params={"user_id": user["id"]})
        assert download_url.status_code == 200, download_url.text
        download_path = urlparse(download_url.json()["url"]).path
        download = self.client.get(download_path)
        assert download.status_code == 200, download.text
        assert download.content == payload

        public_url = self.client.get(f"/files/{file_id}/public-url", params={"user_id": user["id"]})
        assert public_url.status_code == 200, public_url.text
        public_path = urlparse(public_url.json()["url"]).path
        public_download = self.client.get(public_path)
        assert public_download.status_code == 200, public_download.text
        assert public_download.content == payload
