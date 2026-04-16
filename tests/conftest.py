"""
Pytest fixtures. Every test runs against a fresh temp SQLite DB so tests
never touch the real miningedge.db in the project root.
"""

import os
import sys
import importlib
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def fresh_db(monkeypatch, tmp_path):
    """Point db.DB_PATH at a temporary file, re-init schema, reload modules
    that cache the path."""
    import db
    tmp_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(tmp_db))
    db.init_db()
    yield db


@pytest.fixture
def app_client(fresh_db, monkeypatch, tmp_path):
    """A Flask test client with a temp output/logs dir and a logged-in session."""
    import config
    monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(config, "LOGS_DIR", str(tmp_path / "logs"))
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    import app as app_module
    importlib.reload(app_module)  # pick up patched DB_PATH / dirs
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s["logged_in"] = True
        s["username"] = "tester"
    yield client, app_module
