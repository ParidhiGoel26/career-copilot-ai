"""History storage switch tests (Slice 4)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.db import reset_db_for_tests
from utils import auth, user_data
from utils import db_users


@pytest.fixture()
def file_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "false")
    activity = tmp_path / "user_activity"
    activity.mkdir()
    monkeypatch.setattr(user_data, "DATA_DIR", activity)
    yield activity


@pytest.fixture()
def db_mode(monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "true")
    reset_db_for_tests("sqlite:///:memory:")
    user = db_users.create_user("hist@example.com", "secret12", name="Hist")
    yield user


def test_file_mode_resume_search_coach_flow(file_mode):
    uid = "user-file-1"
    resume = user_data.save_resume_record(uid, "abc.pdf", "Resume.pdf")
    assert resume["stored_filename"] == "abc.pdf"

    search = user_data.log_job_search(
        uid, "Senior Engineer\nBuild APIs", resume_id=resume["id"], tool="ats"
    )
    assert search["title"].startswith("Senior Engineer")
    updated = user_data.update_job_search(uid, search["id"], ats_score=88.0)
    assert updated["ats_score"] == 88.0

    user_data.log_coach_query(uid, "How do I improve?")
    history = user_data.get_user_history(uid)
    assert len(history["resumes"]) == 1
    assert len(history["searches"]) == 1
    assert len(history["coach_queries"]) == 1

    path = file_mode / f"{uid}.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["resumes"][0]["id"] == resume["id"]


def test_db_mode_resume_search_coach_flow(db_mode):
    uid = db_mode["id"]
    resume = user_data.save_resume_record(uid, "db.pdf", "DB.pdf")
    search = user_data.log_job_search(
        uid, "Backend Role\nPython", resume_id=resume["id"]
    )
    user_data.update_job_search(uid, search["id"], ats_score=91.5)
    user_data.log_coach_query(uid, "Tell me about ATS")

    history = user_data.get_user_history(uid)
    assert len(history["resumes"]) == 1
    assert history["searches"][0]["ats_score"] == 91.5
    assert history["coach_queries"][0]["message"].startswith("Tell me")

    assert user_data.find_resume(uid, resume["id"])["id"] == resume["id"]
    assert user_data.find_search(uid, search["id"])["id"] == search["id"]


def test_file_mode_delete(file_mode, tmp_path):
    uid = "user-del"
    upload = tmp_path / "uploads"
    upload.mkdir()
    pdf = upload / "gone.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    resume = user_data.save_resume_record(uid, "gone.pdf", "gone.pdf")
    search = user_data.log_job_search(uid, "JD", resume_id=resume["id"])
    assert user_data.delete_resume(uid, resume["id"], str(upload)) is True
    assert not pdf.exists()
    assert user_data.find_resume(uid, resume["id"]) is None
    assert user_data.find_search(uid, search["id"])["resume_id"] is None
    assert user_data.delete_search(uid, search["id"]) is True


def test_db_mode_delete(db_mode, tmp_path):
    uid = db_mode["id"]
    upload = tmp_path / "uploads"
    upload.mkdir()
    pdf = upload / "gone_db.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    resume = user_data.save_resume_record(uid, "gone_db.pdf", "gone.pdf")
    search = user_data.log_job_search(uid, "JD", resume_id=resume["id"])
    assert user_data.delete_resume(uid, resume["id"], str(upload)) is True
    assert not pdf.exists()
    assert user_data.find_resume(uid, resume["id"]) is None
    assert user_data.find_search(uid, search["id"])["resume_id"] is None
    assert user_data.delete_search(uid, search["id"]) is True


def test_flask_history_with_flag_off(file_mode, monkeypatch, tmp_path):
    """History page loads with USE_DATABASE=false after logging a search."""
    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("DEMO_MODE", "true")
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", users_file)
    user = auth.create_user("histfile@careerai.local", "admin123", name="Hist")

    user_data.save_resume_record(user["id"], "r.pdf", "r.pdf")
    user_data.log_job_search(user["id"], "Staff Engineer role")

    from app import app

    client = app.test_client()
    login = client.post(
        "/auth/login",
        data={"email": "histfile@careerai.local", "password": "admin123"},
        follow_redirects=False,
    )
    assert login.status_code in (302, 200)
    page = client.get("/history")
    assert page.status_code == 200
    assert b"Staff Engineer" in page.data


def test_flask_history_with_flag_on(db_mode, monkeypatch):
    """History page loads with USE_DATABASE=true."""
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("DEMO_MODE", "true")
    user = db_mode
    # Need a login-capable user — db_mode already created hist@example.com
    user_data.log_job_search(user["id"], "Principal Engineer opening")

    from app import app

    client = app.test_client()
    login = client.post(
        "/auth/login",
        data={"email": "hist@example.com", "password": "secret12"},
        follow_redirects=False,
    )
    assert login.status_code in (302, 200)
    page = client.get("/history")
    assert page.status_code == 200
    assert b"Principal Engineer" in page.data
