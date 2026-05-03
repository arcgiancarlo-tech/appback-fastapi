import base64
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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_comfyui_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"
os.environ["COMFYUI_CALLBACK_SECRET"] = "comfy-secret"
os.environ["COMFYUI_CALLBACK_CLIENT_ID"] = "bridge-primary"
os.environ["COMFYUI_CALLBACK_CLIENT_SECRET"] = "bridge-client-secret"
os.environ["COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET"] = "comfy-signing-secret"
os.environ["COMFYUI_CALLBACK_TOKEN_TTL_SECONDS"] = "900"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class TestComfyUIEndpoints:
    def setup_method(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_comfyui_endpoints.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{self.test_db_path}"
        os.environ["COMFYUI_CALLBACK_SECRET"] = "comfy-secret"
        os.environ["COMFYUI_CALLBACK_CLIENT_ID"] = "bridge-primary"
        os.environ["COMFYUI_CALLBACK_CLIENT_SECRET"] = "bridge-client-secret"
        os.environ["COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET"] = "comfy-signing-secret"
        os.environ["COMFYUI_CALLBACK_TOKEN_TTL_SECONDS"] = "900"
        importlib.reload(db_module)
        importlib.reload(models_module)
        importlib.reload(schemas_module)
        importlib.reload(crud_module)
        importlib.reload(main_module)
        db_module.Base.metadata.create_all(bind=db_module.engine)
        self.client = TestClient(main_module.app)

    def auth_headers(self, token: str = "comfy-secret"):
        return {"Authorization": f"Bearer {token}"}

    def issue_callback_token(self):
        response = self.client.post(
            "/comfyui/auth/token",
            json={"client_id": "bridge-primary", "client_secret": "bridge-client-secret"},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    def teardown_method(self):
        self.client.close()
        close_all_sessions()
        db_module.engine.dispose()
        self.tmpdir.cleanup()

    def test_comfyui_prompt_submission_status_and_result_callback_flow(self):
        user = self.client.post("/users/", json={"email": "comfy@example.com"}).json()
        template = self.client.post(
            "/templates/",
            json={"name": "Comfy Flow", "description": "desc", "category": "video"},
        ).json()

        upload = self.client.post(
            "/uploads/",
            json={
                "user_id": user["id"],
                "filename": "input.png",
                "mime_type": "image/png",
                "content_base64": base64.b64encode(b"input-image").decode("ascii"),
            },
        )
        assert upload.status_code == 201, upload.text
        input_file = upload.json()

        submit = self.client.post(
            "/comfyui/prompt",
            json={
                "user_id": user["id"],
                "template_id": template["id"],
                "input_file_id": input_file["id"],
                "prompt_id": "prompt-test-123",
                "workflow_key": "hug_video_flux_v3",
                "comfyui_server_id": "server-a",
                "result_kind": "video",
            },
            headers=self.auth_headers(),
        )
        assert submit.status_code == 201, submit.text
        submit_body = submit.json()
        assert submit_body == {
            "prompt_id": "prompt-test-123",
            "generation_id": submit_body["generation_id"],
            "number": submit_body["generation_id"],
            "node_errors": {},
            "status": "queued",
        }

        status_response = self.client.get("/comfyui/history/prompt-test-123")
        assert status_response.status_code == 200, status_response.text
        status_body = status_response.json()
        assert status_body["prompt_id"] == "prompt-test-123"
        assert status_body["status"] == "queued"
        assert status_body["completed"] is False
        assert status_body["failed"] is False
        assert status_body["generation"]["input_file_id"] == input_file["id"]
        assert status_body["generation"]["workflow_key"] == "hug_video_flux_v3"

        callback = self.client.post(
            "/comfyui/history/prompt-test-123/result",
            json={
                "filename": "output.mp4",
                "mime_type": "video/mp4",
                "content_base64": base64.b64encode(b"video-bytes").decode("ascii"),
                "status": "completed",
                "workflow_key": "hug_video_flux_v3",
                "comfyui_server_id": "server-a",
                "result_kind": "video",
            },
            headers=self.auth_headers(),
        )
        assert callback.status_code == 200, callback.text
        callback_body = callback.json()
        assert callback_body["prompt_id"] == "prompt-test-123"
        assert callback_body["status"] == "completed"
        assert callback_body["result_received"] is True
        assert callback_body["output_file_id"] is not None
        assert callback_body["output_path"].endswith("output.mp4")

        final_status = self.client.get("/comfyui/history/prompt-test-123")
        assert final_status.status_code == 200, final_status.text
        final_body = final_status.json()
        assert final_body["completed"] is True
        assert final_body["failed"] is False
        assert final_body["generation"]["output_file"]["kind"] == "generation_output"

    def test_comfyui_result_callback_can_mark_job_failed(self):
        user = self.client.post("/users/", json={"email": "failed@example.com"}).json()
        template = self.client.post(
            "/templates/",
            json={"name": "Broken Flow", "description": "desc", "category": "image"},
        ).json()

        submit = self.client.post(
            "/comfyui/prompt",
            json={
                "user_id": user["id"],
                "template_id": template["id"],
                "input_path": "/tmp/input.png",
                "prompt_id": "prompt-failed-1",
            },
            headers=self.auth_headers(),
        )
        assert submit.status_code == 201, submit.text

        callback = self.client.post(
            "/comfyui/history/prompt-failed-1/result",
            json={
                "status": "failed",
                "error_code": "COMFY_WORKFLOW_ERROR",
                "error_message": "Node execution failed",
            },
            headers=self.auth_headers(),
        )
        assert callback.status_code == 200, callback.text
        body = callback.json()
        assert body["status"] == "failed"
        assert body["result_received"] is False
        assert body["error_code"] == "COMFY_WORKFLOW_ERROR"

        status_response = self.client.get("/comfyui/history/prompt-failed-1")
        assert status_response.status_code == 200, status_response.text
        status_body = status_response.json()
        assert status_body["failed"] is True
        assert status_body["completed"] is False
        assert status_body["error_message"] == "Node execution failed"

    def test_comfyui_write_endpoints_reject_missing_credentials(self):
        user = self.client.post("/users/", json={"email": "unauth@example.com"}).json()
        template = self.client.post(
            "/templates/",
            json={"name": "Auth Flow", "description": "desc", "category": "video"},
        ).json()

        submit = self.client.post(
            "/comfyui/prompt",
            json={
                "user_id": user["id"],
                "template_id": template["id"],
                "input_path": "/tmp/input.png",
                "prompt_id": "prompt-no-auth",
            },
        )
        assert submit.status_code == 401, submit.text

    def test_comfyui_callback_token_can_authenticate_bridge_requests(self):
        token = self.issue_callback_token()

        user = self.client.post("/users/", json={"email": "token@example.com"}).json()
        template = self.client.post(
            "/templates/",
            json={"name": "Token Flow", "description": "desc", "category": "image"},
        ).json()

        created = self.client.post(
            "/generations/",
            json={
                "user_id": user["id"],
                "template_id": template["id"],
                "input_path": "/tmp/input.png",
                "status": "uploaded",
            },
            headers=self.auth_headers(token),
        )
        assert created.status_code == 201, created.text
        generation = created.json()

        status_response = self.client.post(
            f"/generations/{generation['id']}/status",
            json={"status": "queued", "comfyui_job_id": "prompt-token-1"},
            headers=self.auth_headers(token),
        )
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["status"] == "queued"

    def test_comfyui_token_endpoint_rejects_invalid_client_secret(self):
        response = self.client.post(
            "/comfyui/auth/token",
            json={"client_id": "bridge-primary", "client_secret": "wrong"},
        )
        assert response.status_code == 401, response.text
