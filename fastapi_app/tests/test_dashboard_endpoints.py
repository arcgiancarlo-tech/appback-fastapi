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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_dashboard_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


class DashboardEndpointTests(unittest.TestCase):
    def setUp(self):
        db_module.engine.dispose()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.tmpdir.name) / "test_dashboard_endpoints.db"
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

    def create_template(self, name: str, category: str = "general"):
        response = self.client.post(
            "/templates/",
            json={"name": name, "description": f"{name} template", "category": category},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_generation(self, user_id: int, template_id: int, status: str, credits_used: int):
        response = self.client.post(
            "/generations/",
            json={
                "user_id": user_id,
                "template_id": template_id,
                "input_path": f"/tmp/{user_id}-{template_id}-{status}.png",
                "output_path": f"/tmp/{user_id}-{template_id}-{status}-out.png",
                "status": status,
                "credits_used": credits_used,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_credit_pack(self, user_id: int, credits: int, price: float, pack_name: str = "Pack"):
        response = self.client.post(
            "/credit_packs/",
            json={"user_id": user_id, "pack_name": pack_name, "credits": credits, "price": price},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def seed_dashboard_data(self):
        alpha = self.create_user("alpha@example.com")
        beta = self.create_user("beta@example.com")
        hero = self.create_template("Hero Shot", category="photo")
        reel = self.create_template("Promo Reel", category="video")

        self.create_credit_pack(alpha["id"], 100, 29.99, "Alpha Pro")
        self.create_credit_pack(alpha["id"], 25, 9.99, "Alpha Top Up")
        self.create_credit_pack(beta["id"], 50, 14.99, "Beta Starter")

        self.create_generation(alpha["id"], hero["id"], "completed", 12)
        self.create_generation(alpha["id"], hero["id"], "failed", 4)
        self.create_generation(alpha["id"], reel["id"], "pending", 3)
        self.create_generation(beta["id"], reel["id"], "completed", 8)

        return alpha, beta, hero, reel

    def test_admin_dashboard_routes_major_views(self):
        alpha, beta, hero, reel = self.seed_dashboard_data()

        overview = self.client.get("/dashboard/admin/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(overview.json()["total_users"], 2)
        self.assertEqual(overview.json()["total_jobs"], 4)

        users = self.client.get("/dashboard/admin/users", params={"email_query": "alpha"})
        self.assertEqual(users.status_code, 200, users.text)
        self.assertEqual([row["email"] for row in users.json()], ["alpha@example.com"])

        templates = self.client.get("/dashboard/admin/templates")
        self.assertEqual(templates.status_code, 200, templates.text)
        self.assertEqual({row["name"] for row in templates.json()}, {"Hero Shot", "Promo Reel"})

        jobs = self.client.get("/dashboard/admin/jobs", params={"template_id": hero["id"]})
        self.assertEqual(jobs.status_code, 200, jobs.text)
        self.assertEqual(len(jobs.json()), 2)
        self.assertEqual({row["template_name"] for row in jobs.json()}, {"Hero Shot"})

        credits = self.client.get("/dashboard/admin/credits", params={"user_id": alpha["id"]})
        self.assertEqual(credits.status_code, 200, credits.text)
        self.assertEqual(credits.json()["total_users"], 1)
        self.assertEqual(credits.json()["issued_credits"], 125)

        template_usage = self.client.get("/dashboard/admin/template-usage")
        self.assertEqual(template_usage.status_code, 200, template_usage.text)
        self.assertEqual(template_usage.json()["total_generations"], 4)

        jobs_users = self.client.get("/dashboard/admin/jobs/users")
        self.assertEqual(jobs_users.status_code, 200, jobs_users.text)
        self.assertEqual({row["user_email"] for row in jobs_users.json()}, {"alpha@example.com", "beta@example.com"})

        status_breakdown = self.client.get("/dashboard/admin/jobs/status-breakdown")
        self.assertEqual(status_breakdown.status_code, 200, status_breakdown.text)
        self.assertEqual(
            {row["status"]: row["total_jobs"] for row in status_breakdown.json()},
            {"completed": 2, "failed": 1, "pending": 1},
        )

    def test_user_dashboard_routes_overview_jobs_credits_and_templates(self):
        alpha, beta, hero, reel = self.seed_dashboard_data()

        overview = self.client.get(f"/dashboard/users/{alpha['id']}/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        data = overview.json()
        self.assertEqual(data["user"]["email"], "alpha@example.com")
        self.assertEqual(data["credits"]["issued_credits"], 125)
        self.assertEqual(data["credits"]["consumed_credits"], 19)
        self.assertEqual(data["credits"]["remaining_credits"], 106)
        self.assertEqual(data["jobs"]["total_jobs"], 3)
        self.assertEqual(data["jobs"]["completed_jobs"], 1)
        self.assertEqual(data["jobs"]["failed_jobs"], 1)
        self.assertEqual(data["jobs"]["pending_jobs"], 1)
        self.assertEqual(len(data["recent_generations"]), 3)
        self.assertEqual({row["template_name"] for row in data["recent_generations"]}, {"Hero Shot", "Promo Reel"})

        jobs = self.client.get(f"/dashboard/users/{alpha['id']}/jobs", params={"status": "failed"})
        self.assertEqual(jobs.status_code, 200, jobs.text)
        self.assertEqual(len(jobs.json()), 1)
        self.assertEqual(jobs.json()[0]["status"], "failed")

        credits = self.client.get(f"/dashboard/users/{alpha['id']}/credits")
        self.assertEqual(credits.status_code, 200, credits.text)
        self.assertEqual(credits.json(), data["credits"])

        templates = self.client.get(f"/dashboard/users/{alpha['id']}/templates")
        self.assertEqual(templates.status_code, 200, templates.text)
        templates_by_name = {row["template_name"]: row for row in templates.json()}
        self.assertEqual(templates_by_name["Hero Shot"]["generation_count"], 2)
        self.assertEqual(templates_by_name["Promo Reel"]["generation_count"], 1)

        job_summary = self.client.get(f"/dashboard/users/{alpha['id']}/job-summary")
        self.assertEqual(job_summary.status_code, 200, job_summary.text)
        self.assertEqual(job_summary.json(), data["jobs"])

        missing = self.client.get("/dashboard/users/9999/overview")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["detail"], "User not found")


if __name__ == "__main__":
    unittest.main()
