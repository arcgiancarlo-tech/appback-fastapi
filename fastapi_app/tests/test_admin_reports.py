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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_initial_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402


class AdminReportApiTests(unittest.TestCase):
    def setUp(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_admin_reports.db"
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

    def create_user(self, email: str):
        response = self.client.post("/users/", json={"email": email})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_template(self, name: str, description: str = "desc", category: str = "general"):
        response = self.client.post("/admin/templates/", json={"name": name, "description": description, "category": category})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_generation(self, user_id: int, template_id: int, status: str):
        response = self.client.post(
            "/generations/",
            json={
                "user_id": user_id,
                "template_id": template_id,
                "input_path": f"/tmp/{user_id}-{template_id}-{status}.png",
                "output_path": f"/tmp/{user_id}-{template_id}-{status}-out.png",
                "status": status,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_credit_pack(self, user_id: int, pack_name: str, credits: int, price: float):
        response = self.client.post(
            "/credit_packs/",
            json={
                "user_id": user_id,
                "pack_name": pack_name,
                "credits": credits,
                "price": price,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_admin_template_crud_and_soft_delete(self):
        template = self.create_template("Starter", category="fitness")

        fetch_response = self.client.get(f"/admin/templates/{template['id']}")
        self.assertEqual(fetch_response.status_code, 200)
        self.assertEqual(fetch_response.json()["name"], "Starter")

        update_response = self.client.put(
            f"/admin/templates/{template['id']}",
            json={"description": "Updated", "is_active": True, "category": "wellness"},
        )
        self.assertEqual(update_response.status_code, 200)
        body = update_response.json()
        self.assertEqual(body["description"], "Updated")
        self.assertEqual(body["category"], "wellness")

        delete_response = self.client.delete(f"/admin/templates/{template['id']}")
        self.assertEqual(delete_response.status_code, 204)

        public_list = self.client.get("/templates/")
        self.assertEqual(public_list.status_code, 200)
        self.assertEqual(public_list.json(), [])

        admin_list = self.client.get("/admin/templates/")
        self.assertEqual(admin_list.status_code, 200)
        self.assertEqual(len(admin_list.json()), 1)
        self.assertFalse(admin_list.json()[0]["is_active"])

    def test_template_usage_report_aggregates_by_template(self):
        user = self.create_user("reporter@example.com")
        t1 = self.create_template("Portrait Pro", category="photo")
        t2 = self.create_template("Ad Builder", category="marketing")

        self.create_generation(user["id"], t1["id"], "completed")
        self.create_generation(user["id"], t1["id"], "failed")
        self.create_generation(user["id"], t1["id"], "processing")
        self.create_generation(user["id"], t2["id"], "completed")

        report_response = self.client.get("/admin/reports/template-usage")
        self.assertEqual(report_response.status_code, 200, report_response.text)
        report = report_response.json()

        self.assertEqual(report["total_templates"], 2)
        self.assertEqual(report["total_generations"], 4)

        by_name = {item["template_name"]: item for item in report["templates"]}
        self.assertEqual(by_name["Portrait Pro"]["generation_count"], 3)
        self.assertEqual(by_name["Portrait Pro"]["completed_count"], 1)
        self.assertEqual(by_name["Portrait Pro"]["failed_count"], 1)
        self.assertEqual(by_name["Portrait Pro"]["pending_count"], 1)
        self.assertEqual(by_name["Ad Builder"]["generation_count"], 1)
        self.assertEqual(by_name["Ad Builder"]["completed_count"], 1)

    def test_credit_report_summarizes_issued_and_consumed_credits(self):
        user_1 = self.create_user("credits1@example.com")
        user_2 = self.create_user("credits2@example.com")
        template = self.create_template("Usage Template")

        self.create_credit_pack(user_1["id"], "Starter", 50, 9.99)
        self.create_credit_pack(user_1["id"], "Top Up", 20, 4.99)
        self.create_credit_pack(user_2["id"], "Pro", 100, 19.99)

        self.create_generation(user_1["id"], template["id"], "completed")
        self.create_generation(user_1["id"], template["id"], "failed")
        self.create_generation(user_2["id"], template["id"], "processing")

        report_response = self.client.get("/admin/reports/credits", params={"credits_per_generation": 2})
        self.assertEqual(report_response.status_code, 200, report_response.text)
        report = report_response.json()

        self.assertEqual(report["credits_per_generation"], 2)
        self.assertEqual(report["issued_credits"], 170)
        self.assertEqual(report["generation_count"], 3)
        self.assertEqual(report["consumed_credits"], 6)
        self.assertEqual(report["remaining_credits"], 164)
        self.assertEqual(report["purchased_credit_packs"], 3)
        self.assertEqual(report["total_users"], 2)

        by_email = {item["user_email"]: item for item in report["users"]}
        self.assertEqual(by_email["credits1@example.com"]["issued_credits"], 70)
        self.assertEqual(by_email["credits1@example.com"]["consumed_credits"], 4)
        self.assertEqual(by_email["credits1@example.com"]["remaining_credits"], 66)
        self.assertEqual(by_email["credits1@example.com"]["failed_generation_count"], 1)
        self.assertEqual(by_email["credits2@example.com"]["issued_credits"], 100)
        self.assertEqual(by_email["credits2@example.com"]["pending_generation_count"], 1)

        user_filtered = self.client.get(f"/admin/reports/credits?user_id={user_1['id']}")
        self.assertEqual(user_filtered.status_code, 200)
        filtered_report = user_filtered.json()
        self.assertEqual(filtered_report["total_users"], 1)
        self.assertEqual(filtered_report["issued_credits"], 70)
        self.assertEqual(filtered_report["generation_count"], 2)

    def test_job_reports_support_template_filtering_and_status_breakdown(self):
        user_1 = self.create_user("jobs1@example.com")
        user_2 = self.create_user("jobs2@example.com")
        portrait = self.create_template("Portrait Pro", category="photo")
        banner = self.create_template("Banner Builder", category="ads")

        self.create_generation(user_1["id"], portrait["id"], "completed")
        self.create_generation(user_1["id"], portrait["id"], "failed")
        self.create_generation(user_2["id"], portrait["id"], "pending")
        self.create_generation(user_2["id"], banner["id"], "completed")

        jobs_response = self.client.get("/admin/jobs/", params={"template_id": portrait["id"]})
        self.assertEqual(jobs_response.status_code, 200, jobs_response.text)
        jobs = jobs_response.json()
        self.assertEqual(len(jobs), 3)
        self.assertEqual({job["template_name"] for job in jobs}, {"Portrait Pro"})
        self.assertEqual({job["user_email"] for job in jobs}, {"jobs1@example.com", "jobs2@example.com"})

        user_stats_response = self.client.get("/admin/reports/jobs/users", params={"template_id": portrait["id"]})
        self.assertEqual(user_stats_response.status_code, 200, user_stats_response.text)
        user_stats = {item["user_email"]: item for item in user_stats_response.json()}
        self.assertEqual(user_stats["jobs1@example.com"]["total_jobs"], 2)
        self.assertEqual(user_stats["jobs1@example.com"]["completed_jobs"], 1)
        self.assertEqual(user_stats["jobs1@example.com"]["failed_jobs"], 1)
        self.assertEqual(user_stats["jobs2@example.com"]["total_jobs"], 1)
        self.assertEqual(user_stats["jobs2@example.com"]["pending_jobs"], 1)

        breakdown_response = self.client.get(
            "/admin/reports/jobs/status-breakdown",
            params={"template_id": portrait["id"]},
        )
        self.assertEqual(breakdown_response.status_code, 200, breakdown_response.text)
        breakdown = {item["status"]: item["total_jobs"] for item in breakdown_response.json()}
        self.assertEqual(breakdown, {"completed": 1, "failed": 1, "pending": 1})


if __name__ == "__main__":
    unittest.main()
