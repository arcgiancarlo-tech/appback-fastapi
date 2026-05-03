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

INITIAL_DB_PATH = Path(tempfile.gettempdir()) / "fastapi_app_admin_template_page_display_configs_initial.db"
os.environ["DATABASE_URL"] = f"sqlite:///{INITIAL_DB_PATH}"

from fastapi_app import crud as crud_module  # noqa: E402
from fastapi_app import db as db_module  # noqa: E402
from fastapi_app import main as main_module  # noqa: E402
from fastapi_app import models as models_module  # noqa: E402
from fastapi_app import schemas as schemas_module  # noqa: E402


client = None
tmpdir = None


def setup_function():
    global client, tmpdir
    db_module.engine.dispose()
    tmpdir = tempfile.TemporaryDirectory()
    test_db_path = Path(tmpdir.name) / "test_admin_template_page_display_configs.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path}"
    importlib.reload(db_module)
    importlib.reload(models_module)
    importlib.reload(schemas_module)
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


def seed_categories():
    anime = client.post("/admin/categories", json={"name": "Anime", "is_active": True}).json()
    portrait = client.post("/admin/categories", json={"name": "Portrait", "is_active": True}).json()
    spicy = client.post("/admin/categories", json={"name": "Spicy", "is_active": True}).json()
    hidden = client.post("/admin/categories", json={"name": "Hidden", "is_active": False}).json()
    return anime, portrait, spicy, hidden


def test_template_page_display_config_admin_crud_and_sorting():
    anime, portrait, spicy, _ = seed_categories()

    create_one = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": portrait["id"], "order": 1},
    )
    assert create_one.status_code == 201, create_one.text

    create_two = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": anime["id"], "order": 0},
    )
    assert create_two.status_code == 201, create_two.text

    create_three = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "spicy_templates", "category_id": spicy["id"], "order": 0},
    )
    assert create_three.status_code == 201, create_three.text

    listing = client.get("/admin/template-page-display-configs")
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert [(row["page_type"], row["category"]["name"], row["order"]) for row in payload] == [
        ("spicy_templates", "Spicy", 0),
        ("templates", "Anime", 0),
        ("templates", "Portrait", 1),
    ]

    filtered = client.get("/admin/template-page-display-configs", params={"page_type": "main_templates"})
    assert filtered.status_code == 200, filtered.text
    assert [row["category"]["name"] for row in filtered.json()] == ["Anime", "Portrait"]

    config_id = create_one.json()["id"]
    updated = client.put(
        f"/admin/template-page-display-configs/{config_id}",
        json={"page_type": "spicy_templates", "category_id": spicy["id"], "order": 1},
    )
    assert updated.status_code == 400, updated.text

    updated = client.put(
        f"/admin/template-page-display-configs/{config_id}",
        json={"page_type": "templates", "category_id": portrait["id"], "order": 2},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["order"] == 2

    get_one = client.get(f"/admin/template-page-display-configs/{config_id}")
    assert get_one.status_code == 200
    assert get_one.json()["category"]["name"] == "Portrait"

    deleted = client.delete(f"/admin/template-page-display-configs/{config_id}")
    assert deleted.status_code == 204, deleted.text
    missing = client.get(f"/admin/template-page-display-configs/{config_id}")
    assert missing.status_code == 404


def test_template_page_display_config_public_endpoint_filters_to_active_categories():
    anime, _, _, hidden = seed_categories()

    visible = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": anime["id"], "order": 0},
    )
    assert visible.status_code == 201, visible.text

    hidden_config = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": hidden["id"], "order": 1},
    )
    assert hidden_config.status_code == 201, hidden_config.text

    public_response = client.get("/templates/page-display-configs", params={"page_type": "templates"})
    assert public_response.status_code == 200, public_response.text
    assert [row["category"]["name"] for row in public_response.json()] == ["Anime"]


def test_template_page_display_config_rejects_duplicate_category_and_order_per_page_type():
    anime, portrait, _, _ = seed_categories()

    first = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": anime["id"], "order": 0},
    )
    assert first.status_code == 201, first.text

    duplicate_category = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": anime["id"], "order": 1},
    )
    assert duplicate_category.status_code == 400
    assert "only appear once" in duplicate_category.json()["detail"]

    duplicate_order = client.post(
        "/admin/template-page-display-configs",
        json={"page_type": "templates", "category_id": portrait["id"], "order": 0},
    )
    assert duplicate_order.status_code == 400
    assert "order value" in duplicate_order.json()["detail"]
