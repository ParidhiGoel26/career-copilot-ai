"""Pytest suite for database models (Slice 1 — no route changes)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.db import get_session, reset_db_for_tests
from utils.models import CoachQuery, JobSearch, Resume, User


@pytest.fixture()
def db_session():
    reset_db_for_tests("sqlite:///:memory:")
    session = get_session()
    try:
        yield session
        session.commit()
    finally:
        session.close()


def test_create_user(db_session):
    user = User(
        email="alice@example.com",
        name="Alice",
        password_hash=generate_password_hash("secret12"),
    )
    db_session.add(user)
    db_session.commit()

    found = db_session.query(User).filter_by(email="alice@example.com").one()
    assert found.id
    assert found.name == "Alice"
    assert found.password_hash.startswith("scrypt:") or found.password_hash.startswith("pbkdf2:")


def test_user_email_unique(db_session):
    db_session.add(User(email="dup@example.com", name="A", password_hash="x"))
    db_session.commit()

    db_session.add(User(email="dup@example.com", name="B", password_hash="y"))
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_create_resume_and_search(db_session):
    user = User(email="bob@example.com", name="Bob", password_hash="hash")
    db_session.add(user)
    db_session.flush()

    resume = Resume(
        user_id=user.id,
        stored_filename="abc_resume.pdf",
        original_filename="Resume.pdf",
    )
    db_session.add(resume)
    db_session.flush()

    search = JobSearch(
        user_id=user.id,
        resume_id=resume.id,
        tool="resume_optimizer",
        title="Python Developer",
        jd_text="Looking for Python Flask engineer",
        ats_score=82.0,
    )
    db_session.add(search)
    db_session.commit()

    refreshed = db_session.get(User, user.id)
    assert len(refreshed.resumes) == 1
    assert len(refreshed.searches) == 1
    assert refreshed.searches[0].resume_id == resume.id
    assert refreshed.searches[0].ats_score == 82.0


def test_delete_user_cascades(db_session):
    user = User(email="cascade@example.com", name="C", password_hash="h")
    db_session.add(user)
    db_session.flush()
    db_session.add(Resume(user_id=user.id, stored_filename="a.pdf", original_filename="a.pdf"))
    db_session.add(JobSearch(user_id=user.id, title="JD", jd_text="text"))
    db_session.add(CoachQuery(user_id=user.id, message="How do I improve?"))
    db_session.commit()

    uid = user.id
    db_session.delete(user)
    db_session.commit()

    assert db_session.query(Resume).filter_by(user_id=uid).count() == 0
    assert db_session.query(JobSearch).filter_by(user_id=uid).count() == 0
    assert db_session.query(CoachQuery).filter_by(user_id=uid).count() == 0
