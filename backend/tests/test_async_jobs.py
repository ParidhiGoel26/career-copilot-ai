"""Async job queue tests (Week 2 / JD upgrade)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.feature_flags import use_async_jobs
from utils.jobs import MemoryJobManager, reset_job_manager_for_tests
from utils import auth, metrics


def test_job_manager_runs_and_completes(tmp_path):
    mgr = MemoryJobManager(max_workers=1)
    payload = {
        "resume_text": "Engineer with Flask experience.",
        "jd_text": "Looking for Flask backend engineer.",
        "tone": "professional",
        "demo_mode": True,
        "upload_folder": str(tmp_path),
        "store_id": "teststore",
    }
    job_id = mgr.submit("cover_letter", payload, user_id="u1")
    deadline = time.time() + 20
    while time.time() < deadline:
        job = mgr.get(job_id, user_id="u1")
        if job and job.status in ("done", "failed"):
            break
        time.sleep(0.05)
    job = mgr.get(job_id, user_id="u1")
    assert job is not None
    assert job.status == "done", job.error
    assert "content" in job.result


def test_job_manager_isolates_users(tmp_path):
    mgr = MemoryJobManager(max_workers=1)
    payload = {
        "resume_text": "x",
        "jd_text": "y",
        "tone": "professional",
        "demo_mode": True,
        "upload_folder": str(tmp_path),
        "store_id": "iso",
    }
    job_id = mgr.submit("cover_letter", payload, user_id="owner")
    time.sleep(0.2)
    assert mgr.get(job_id, user_id="owner") is not None
    assert mgr.get(job_id, user_id="other") is None


def test_job_manager_captures_failure():
    mgr = MemoryJobManager(max_workers=1)
    job_id = mgr.submit("unknown_type_xyz", {}, user_id="u1")
    deadline = time.time() + 2
    while time.time() < deadline:
        job = mgr.get(job_id)
        if job.status in ("done", "failed"):
            break
        time.sleep(0.02)
    job = mgr.get(job_id)
    assert job.status == "failed"
    assert job.error


@pytest.fixture()
def sync_client(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_ASYNC_JOBS", "false")
    monkeypatch.setenv("JOB_BACKEND", "memory")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("USE_DATABASE", "false")
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", users_file)
    auth.create_user("async@careerai.local", "admin123", name="Async")
    reset_job_manager_for_tests()
    metrics.reset_for_tests()

    from app import app

    client = app.test_client()
    client.post(
        "/auth/login",
        data={"email": "async@careerai.local", "password": "admin123"},
        follow_redirects=False,
    )
    yield client


@pytest.fixture()
def async_client(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_ASYNC_JOBS", "true")
    monkeypatch.setenv("JOB_BACKEND", "memory")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("USE_DATABASE", "false")
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(auth, "USERS_FILE", users_file)
    auth.create_user("async2@careerai.local", "admin123", name="Async")
    reset_job_manager_for_tests()
    metrics.reset_for_tests()

    from app import app

    client = app.test_client()
    client.post(
        "/auth/login",
        data={"email": "async2@careerai.local", "password": "admin123"},
        follow_redirects=False,
    )
    yield client


def test_flag_defaults_false(monkeypatch):
    monkeypatch.delenv("USE_ASYNC_JOBS", raising=False)
    assert use_async_jobs() is False


def test_coach_sync_when_flag_off(sync_client):
    resp = sync_client.post(
        "/career-coach/chat",
        json={"message": "What projects stand out?"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reply" in data
    assert "job_id" not in data


def test_coach_async_returns_job_and_polls(async_client):
    resp = async_client.post(
        "/career-coach/chat",
        json={"message": "Summarize my strengths"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    deadline = time.time() + 8
    final = None
    while time.time() < deadline:
        poll = async_client.get(f"/jobs/{job_id}")
        assert poll.status_code == 200
        final = poll.get_json()
        if final["status"] in ("done", "failed"):
            break
        time.sleep(0.05)

    assert final is not None
    assert final["status"] == "done"
    assert "reply" in final["result"]


def test_health_and_ready_public(monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import app

    client = app.test_client()
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.get_json()["status"] == "ready"
    assert client.get("/metrics").status_code == 200
