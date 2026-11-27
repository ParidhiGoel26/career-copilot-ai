"""Database-backed history repository (Slice 2).

Mirrors utils.user_data function shapes so Slice 4 can switch storage safely.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from utils.db import get_session
from utils.models import CoachQuery, JobSearch, Resume


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _jd_title(jd_text: str) -> str:
    text = (jd_text or "").strip()
    if not text:
        return "Untitled search"
    first_line = text.split("\n", 1)[0].strip()
    if len(first_line) > 80:
        return first_line[:77] + "..."
    return first_line or "Job description"


def _resume_dict(row: Resume) -> dict:
    return {
        "id": row.id,
        "stored_filename": row.stored_filename,
        "original_filename": row.original_filename,
        "uploaded_at": _iso(row.uploaded_at),
    }


def _search_dict(row: JobSearch) -> dict:
    return {
        "id": row.id,
        "type": "job_description",
        "tool": row.tool,
        "title": row.title,
        "jd_text": row.jd_text,
        "resume_id": row.resume_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "ats_score": row.ats_score,
        "readiness_score": row.readiness_score,
    }


def _coach_dict(row: CoachQuery) -> dict:
    return {
        "id": row.id,
        "message": row.message,
        "created_at": _iso(row.created_at),
    }


def save_resume_record(user_id: str, stored_filename: str, original_filename: str) -> dict:
    session = get_session()
    try:
        row = Resume(
            user_id=user_id,
            stored_filename=stored_filename,
            original_filename=original_filename,
            uploaded_at=_now(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _resume_dict(row)
    finally:
        session.close()


def log_job_search(
    user_id: str,
    jd_text: str,
    *,
    resume_id: str | None = None,
    tool: str = "resume_optimizer",
    extra: dict | None = None,
) -> dict:
    session = get_session()
    try:
        row = JobSearch(
            user_id=user_id,
            resume_id=resume_id,
            tool=tool,
            title=_jd_title(jd_text),
            jd_text=jd_text or "",
            created_at=_now(),
            ats_score=None,
            readiness_score=None,
        )
        if extra:
            if "ats_score" in extra:
                row.ats_score = extra.get("ats_score")
            if "readiness_score" in extra:
                row.readiness_score = extra.get("readiness_score")
            if "title" in extra and extra["title"]:
                row.title = str(extra["title"])
            if "tool" in extra and extra["tool"]:
                row.tool = str(extra["tool"])
        session.add(row)
        session.commit()
        session.refresh(row)
        return _search_dict(row)
    finally:
        session.close()


def update_job_search(user_id: str, search_id: str, **fields) -> dict | None:
    session = get_session()
    try:
        row = (
            session.query(JobSearch)
            .filter_by(id=search_id, user_id=user_id)
            .one_or_none()
        )
        if not row:
            return None

        for key in ("ats_score", "readiness_score", "title", "tool", "jd_text", "resume_id"):
            if key in fields:
                setattr(row, key, fields[key])
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _search_dict(row)
    finally:
        session.close()


def log_coach_query(user_id: str, message: str) -> None:
    session = get_session()
    try:
        session.add(
            CoachQuery(
                user_id=user_id,
                message=(message or "")[:500],
                created_at=_now(),
            )
        )
        session.commit()
    finally:
        session.close()


def get_user_history(user_id: str) -> dict:
    session = get_session()
    try:
        resumes = (
            session.query(Resume)
            .filter_by(user_id=user_id)
            .order_by(Resume.uploaded_at.desc())
            .limit(50)
            .all()
        )
        searches = (
            session.query(JobSearch)
            .filter_by(user_id=user_id)
            .order_by(JobSearch.created_at.desc())
            .limit(100)
            .all()
        )
        coach_queries = (
            session.query(CoachQuery)
            .filter_by(user_id=user_id)
            .order_by(CoachQuery.created_at.desc())
            .limit(100)
            .all()
        )
        return {
            "user_id": user_id,
            "resumes": [_resume_dict(r) for r in resumes],
            "searches": [_search_dict(s) for s in searches],
            "coach_queries": [_coach_dict(c) for c in coach_queries],
        }
    finally:
        session.close()


def find_resume(user_id: str, resume_id: str) -> dict | None:
    session = get_session()
    try:
        row = (
            session.query(Resume)
            .filter_by(id=resume_id, user_id=user_id)
            .one_or_none()
        )
        return _resume_dict(row) if row else None
    finally:
        session.close()


def find_search(user_id: str, search_id: str) -> dict | None:
    session = get_session()
    try:
        row = (
            session.query(JobSearch)
            .filter_by(id=search_id, user_id=user_id)
            .one_or_none()
        )
        return _search_dict(row) if row else None
    finally:
        session.close()


def delete_resume(user_id: str, resume_id: str, user_upload_dir: str) -> bool:
    session = get_session()
    try:
        row = (
            session.query(Resume)
            .filter_by(id=resume_id, user_id=user_id)
            .one_or_none()
        )
        if not row:
            return False

        stored = row.stored_filename
        for search in session.query(JobSearch).filter_by(user_id=user_id, resume_id=resume_id):
            search.resume_id = None
        session.delete(row)
        session.commit()

        if stored and user_upload_dir:
            path = os.path.join(user_upload_dir, stored)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return True
    finally:
        session.close()


def delete_search(user_id: str, search_id: str) -> bool:
    session = get_session()
    try:
        row = (
            session.query(JobSearch)
            .filter_by(id=search_id, user_id=user_id)
            .one_or_none()
        )
        if not row:
            return False
        session.delete(row)
        session.commit()
        return True
    finally:
        session.close()
