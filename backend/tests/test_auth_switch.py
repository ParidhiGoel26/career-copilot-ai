"""Auth storage switch tests (Slice 3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.db import reset_db_for_tests
from utils import auth


@pytest.fixture()
def file_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "false")
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", users_file)
    yield users_file


@pytest.fixture()
def db_mode(monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "true")
    reset_db_for_tests("sqlite:///:memory:")
    yield


def test_file_mode_create_login_and_token(file_mode):
    user = auth.create_user("file@example.com", "secret12", name="File")
    assert user["email"] == "file@example.com"

    logged_in = auth.authenticate_user("file@example.com", "secret12")
    assert logged_in["id"] == user["id"]

    token = auth.create_access_token(logged_in)
    verified = auth.verify_access_token(token)
    assert verified["email"] == "file@example.com"

    data = json.loads(file_mode.read_text(encoding="utf-8"))
    assert len(data["users"]) == 1


def test_db_mode_create_login_and_token(db_mode):
    user = auth.create_user("db@example.com", "secret12", name="DB")
    assert user["email"] == "db@example.com"

    logged_in = auth.authenticate_user("db@example.com", "secret12")
    assert logged_in["id"] == user["id"]
    assert auth.authenticate_user("db@example.com", "nope") is None

    token = auth.create_access_token(logged_in)
    verified = auth.verify_access_token(token)
    assert verified["id"] == user["id"]


def test_ensure_default_user_file_mode(file_mode, monkeypatch):
    monkeypatch.setenv("DEFAULT_USER_EMAIL", "admin@file.local")
    monkeypatch.setenv("DEFAULT_USER_PASSWORD", "admin123")
    auth.ensure_default_user()
    auth.ensure_default_user()
    data = json.loads(file_mode.read_text(encoding="utf-8"))
    assert len(data["users"]) == 1
    assert data["users"][0]["email"] == "admin@file.local"


def test_ensure_default_user_db_mode(db_mode, monkeypatch):
    monkeypatch.setenv("DEFAULT_USER_EMAIL", "admin@db.local")
    monkeypatch.setenv("DEFAULT_USER_PASSWORD", "admin123")
    auth.ensure_default_user()
    auth.ensure_default_user()
    user = auth.authenticate_user("admin@db.local", "admin123")
    assert user is not None


def test_flask_login_with_flag_off(file_mode, monkeypatch):
    """Flask login route works with USE_DATABASE=false (default path)."""
    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("DEMO_MODE", "true")
    auth.create_user("admin@careerai.local", "admin123", name="Admin")

    from app import app

    client = app.test_client()
    resp = client.post(
        "/auth/login",
        data={"email": "admin@careerai.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)
    assert "access_token" in (resp.headers.get("Set-Cookie") or "")

    dash = client.get("/dashboard")
    assert dash.status_code == 200


def test_flask_login_with_flag_on(db_mode, monkeypatch):
    """Flask login route works with USE_DATABASE=true."""
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DEMO_MODE", "true")
    auth.create_user("dbadmin@careerai.local", "admin123", name="Admin")

    from app import app

    client = app.test_client()
    resp = client.post(
        "/auth/login",
        data={"email": "dbadmin@careerai.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)
    assert "access_token" in (resp.headers.get("Set-Cookie") or "")
