"""JSON → DB migration tests (Slice 5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.db import get_session, reset_db_for_tests
from utils.migrate_to_db import run_migration
from utils.models import CoachQuery, JobSearch, Resume, User
from utils import auth, user_data


@pytest.fixture()
def json_sources(tmp_path):
    users_file = tmp_path / "users.json"
    activity = tmp_path / "user_activity"
    activity.mkdir()

    users_file.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                        "email": "alice@example.com",
                        "name": "Alice",
                        "password_hash": "scrypt:fakehash",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                    {
                        "id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                        "email": "bob@example.com",
                        "name": "Bob",
                        "password_hash": "scrypt:fakehash2",
                        "created_at": "2026-01-02T00:00:00+00:00",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    (activity / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json").write_text(
        json.dumps(
            {
                "user_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "resumes": [
                    {
                        "id": "rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr",
                        "stored_filename": "a.pdf",
                        "original_filename": "Alice.pdf",
                        "uploaded_at": "2026-01-03T00:00:00+00:00",
                    }
                ],
                "searches": [
                    {
                        "id": "ssssssssssssssssssssssssssssssss",
                        "tool": "ats",
                        "title": "Staff Eng",
                        "jd_text": "Staff Eng\nPython",
                        "resume_id": "rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr",
                        "created_at": "2026-01-04T00:00:00+00:00",
                        "ats_score": 90.0,
                    }
                ],
                "coach_queries": [
                    {
                        "id": "cccccccccccccccccccccccccccccccc",
                        "message": "How do I prep?",
                        "created_at": "2026-01-05T00:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # Orphan activity (no matching user) should be skipped
    (activity / "deadbeefdeadbeefdeadbeefdeadbeef.json").write_text(
        json.dumps({"user_id": "deadbeefdeadbeefdeadbeefdeadbeef", "resumes": []}),
        encoding="utf-8",
    )
    return users_file, activity


def test_migrate_preserves_ids_and_is_idempotent(json_sources, tmp_path):
    users_file, activity = json_sources
    db_path = tmp_path / "mig.db"
    url = f"sqlite:///{db_path.as_posix()}"

    stats1 = run_migration(users_file=users_file, activity_dir=activity, database_url=url)
    assert stats1["users_added"] == 2
    assert stats1["resumes_added"] == 1
    assert stats1["searches_added"] == 1
    assert stats1["coach_added"] == 1
    assert stats1["orphan_profiles"] == 1

    session = get_session()
    try:
        assert session.get(User, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa").email == "alice@example.com"
        assert session.get(Resume, "rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr").stored_filename == "a.pdf"
        search = session.get(JobSearch, "ssssssssssssssssssssssssssssssss")
        assert search.ats_score == 90.0
        assert search.resume_id == "rrrrrrrrrrrrrrrrrrrrrrrrrrrrrrrr"
        assert session.get(CoachQuery, "cccccccccccccccccccccccccccccccc").message == "How do I prep?"
        assert session.query(User).count() == 2
    finally:
        session.close()

    stats2 = run_migration(users_file=users_file, activity_dir=activity, database_url=url)
    assert stats2["users_added"] == 0
    assert stats2["users_skipped"] == 2
    assert stats2["resumes_added"] == 0
    assert stats2["searches_added"] == 0
    assert stats2["coach_added"] == 0


def test_login_and_history_after_migration(json_sources, tmp_path, monkeypatch):
    users_file, activity = json_sources
    # Patch password hash to a real one so authenticate works
    from werkzeug.security import generate_password_hash

    data = json.loads(users_file.read_text(encoding="utf-8"))
    data["users"][0]["password_hash"] = generate_password_hash("secret12")
    users_file.write_text(json.dumps(data), encoding="utf-8")

    db_path = tmp_path / "auth.db"
    url = f"sqlite:///{db_path.as_posix()}"
    run_migration(users_file=users_file, activity_dir=activity, database_url=url)

    monkeypatch.setenv("USE_DATABASE", "true")
    reset_db_for_tests(url)  # re-attach to same file DB

    user = auth.authenticate_user("alice@example.com", "secret12")
    assert user is not None
    assert user["id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    history = user_data.get_user_history(user["id"])
    assert len(history["resumes"]) == 1
    assert history["searches"][0]["title"] == "Staff Eng"
    assert history["coach_queries"][0]["message"] == "How do I prep?"
