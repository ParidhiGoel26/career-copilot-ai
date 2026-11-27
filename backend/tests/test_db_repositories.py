"""Tests for DB repositories (Slice 2) — no Flask route wiring."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.db import reset_db_for_tests
from utils import db_users, db_history
from utils.feature_flags import use_database


@pytest.fixture()
def fresh_db(monkeypatch):
    monkeypatch.delenv("USE_DATABASE", raising=False)
    reset_db_for_tests("sqlite:///:memory:")
    yield


def test_use_database_flag_defaults_false(monkeypatch):
    monkeypatch.delenv("USE_DATABASE", raising=False)
    assert use_database() is False


def test_use_database_flag_true(monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "true")
    assert use_database() is True


def test_create_and_authenticate_user(fresh_db):
    user = db_users.create_user("repo@example.com", "secret12", name="Repo User")
    assert user["email"] == "repo@example.com"
    assert user["name"] == "Repo User"
    assert "password_hash" not in user

    ok = db_users.authenticate_user("repo@example.com", "secret12")
    assert ok is not None
    assert ok["id"] == user["id"]

    bad = db_users.authenticate_user("repo@example.com", "wrongpass")
    assert bad is None


def test_create_user_duplicate_raises(fresh_db):
    db_users.create_user("dup2@example.com", "secret12")
    with pytest.raises(ValueError, match="already exists"):
        db_users.create_user("dup2@example.com", "secret12")


def test_ensure_default_user(fresh_db, monkeypatch):
    monkeypatch.setenv("DEFAULT_USER_EMAIL", "admin@test.local")
    monkeypatch.setenv("DEFAULT_USER_PASSWORD", "admin123")
    assert db_users.count_users() == 0
    db_users.ensure_default_user()
    assert db_users.count_users() == 1
    db_users.ensure_default_user()  # idempotent
    assert db_users.count_users() == 1


def test_history_resume_search_coach_flow(fresh_db):
    user = db_users.create_user("hist@example.com", "secret12", name="Hist")

    resume = db_history.save_resume_record(user["id"], "abc_file.pdf", "Resume.pdf")
    assert resume["original_filename"] == "Resume.pdf"

    search = db_history.log_job_search(
        user["id"],
        "Senior Python Engineer\nBuild APIs with Flask",
        resume_id=resume["id"],
        tool="resume_optimizer",
    )
    assert "Python" in search["title"]
    assert search["resume_id"] == resume["id"]

    updated = db_history.update_job_search(user["id"], search["id"], ats_score=91.0)
    assert updated["ats_score"] == 91.0

    db_history.log_coach_query(user["id"], "How do I improve my resume?")

    history = db_history.get_user_history(user["id"])
    assert len(history["resumes"]) == 1
    assert len(history["searches"]) == 1
    assert len(history["coach_queries"]) == 1
    assert db_history.find_resume(user["id"], resume["id"])["id"] == resume["id"]
    assert db_history.find_search(user["id"], search["id"])["id"] == search["id"]


def test_delete_resume_and_search(fresh_db):
    user = db_users.create_user("del@example.com", "secret12")
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "gone.pdf")
        with open(pdf_path, "w", encoding="utf-8") as f:
            f.write("x")

        resume = db_history.save_resume_record(user["id"], "gone.pdf", "gone.pdf")
        search = db_history.log_job_search(
            user["id"], "JD text", resume_id=resume["id"], tool="analysis"
        )

        assert db_history.delete_resume(user["id"], resume["id"], tmp) is True
        assert not os.path.exists(pdf_path)
        assert db_history.find_resume(user["id"], resume["id"]) is None

        # linked search remains, resume_id cleared
        found = db_history.find_search(user["id"], search["id"])
        assert found is not None
        assert found["resume_id"] is None

        assert db_history.delete_search(user["id"], search["id"]) is True
        assert db_history.find_search(user["id"], search["id"]) is None
