import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi_app import db as db_module  # noqa: E402


_ORIGINAL_DATABASE_URL = os.environ.get("DATABASE_URL")


def teardown_function():
    db_module.engine.dispose()
    if _ORIGINAL_DATABASE_URL is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = _ORIGINAL_DATABASE_URL
    importlib.reload(db_module)


def test_defaults_to_in_memory_sqlite_during_pytest_when_database_url_missing():
    os.environ.pop("DATABASE_URL", None)

    importlib.reload(db_module)

    assert db_module.DATABASE_URL == "sqlite:///:memory:"
    assert db_module.engine.url.get_backend_name() == "sqlite"
    assert db_module.engine.url.database in {":memory:", None}


def test_local_dev_default_sqlite_path_constant_is_documented_for_non_test_runs():
    assert db_module.DEFAULT_SQLITE_URL.endswith("fastapi_app/dev.db")


def test_normalizes_postgres_scheme_for_production_database_urls():
    os.environ["DATABASE_URL"] = "postgres://user:pass@db.example.com:5432/appdb"

    assert db_module.get_database_url() == "postgresql://user:pass@db.example.com:5432/appdb"
