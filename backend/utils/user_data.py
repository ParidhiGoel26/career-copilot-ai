"""Per-user storage for uploaded resumes and job-description searches.

Dispatches to JSON files (default) or utils.db_history when USE_DATABASE is on.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from utils.feature_flags import use_database

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "user_activity"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile_path(user_id: str) -> Path:
    return DATA_DIR / f"{user_id}.json"


def _load_profile(user_id: str) -> dict:
    path = _profile_path(user_id)
    if not path.exists():
        return {
            "user_id": user_id,
            "resumes": [],
            "searches": [],
            "coach_queries": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("resumes", [])
        data.setdefault("searches", [])
        data.setdefault("coach_queries", [])
        return data
    except (json.JSONDecodeError, OSError):
        return {
            "user_id": user_id,
            "resumes": [],
            "searches": [],
            "coach_queries": [],
        }


def _save_profile(user_id: str, data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["user_id"] = user_id
    _profile_path(user_id).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _jd_title(jd_text: str) -> str:
    text = (jd_text or "").strip()
    if not text:
        return "Untitled search"
    first_line = text.split("\n", 1)[0].strip()
    if len(first_line) > 80:
        return first_line[:77] + "..."
    return first_line or "Job description"


def _file_save_resume_record(user_id: str, stored_filename: str, original_filename: str) -> dict:
    profile = _load_profile(user_id)
    record = {
        "id": uuid.uuid4().hex,
        "stored_filename": stored_filename,
        "original_filename": original_filename,
        "uploaded_at": _now(),
    }
    profile["resumes"].insert(0, record)
    profile["resumes"] = profile["resumes"][:50]
    _save_profile(user_id, profile)
    return record


def _file_log_job_search(
    user_id: str,
    jd_text: str,
    *,
    resume_id: str | None = None,
    tool: str = "resume_optimizer",
    extra: dict | None = None,
) -> dict:
    profile = _load_profile(user_id)
    record = {
        "id": uuid.uuid4().hex,
        "type": "job_description",
        "tool": tool,
        "title": _jd_title(jd_text),
        "jd_text": jd_text,
        "resume_id": resume_id,
        "created_at": _now(),
        "ats_score": None,
        "readiness_score": None,
    }
    if extra:
        record.update(extra)
    profile["searches"].insert(0, record)
    profile["searches"] = profile["searches"][:100]
    _save_profile(user_id, profile)
    return record


def _file_update_job_search(user_id: str, search_id: str, **fields) -> dict | None:
    profile = _load_profile(user_id)
    for item in profile["searches"]:
        if item.get("id") == search_id:
            item.update(fields)
            item["updated_at"] = _now()
            _save_profile(user_id, profile)
            return item
    return None


def _file_log_coach_query(user_id: str, message: str) -> None:
    profile = _load_profile(user_id)
    profile["coach_queries"].insert(0, {
        "id": uuid.uuid4().hex,
        "message": (message or "")[:500],
        "created_at": _now(),
    })
    profile["coach_queries"] = profile["coach_queries"][:100]
    _save_profile(user_id, profile)


def _file_get_user_history(user_id: str) -> dict:
    return _load_profile(user_id)


def _file_find_resume(user_id: str, resume_id: str) -> dict | None:
    for item in _load_profile(user_id).get("resumes", []):
        if item.get("id") == resume_id:
            return item
    return None


def _file_find_search(user_id: str, search_id: str) -> dict | None:
    for item in _load_profile(user_id).get("searches", []):
        if item.get("id") == search_id:
            return item
    return None


def _file_delete_resume(user_id: str, resume_id: str, user_upload_dir: str) -> bool:
    profile = _load_profile(user_id)
    record = None
    remaining = []
    for item in profile.get("resumes", []):
        if item.get("id") == resume_id:
            record = item
        else:
            remaining.append(item)
    if not record:
        return False

    profile["resumes"] = remaining
    for search in profile.get("searches", []):
        if search.get("resume_id") == resume_id:
            search["resume_id"] = None
    _save_profile(user_id, profile)

    stored = record.get("stored_filename")
    if stored and user_upload_dir:
        path = os.path.join(user_upload_dir, stored)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    return True


def _file_delete_search(user_id: str, search_id: str) -> bool:
    profile = _load_profile(user_id)
    before = len(profile.get("searches", []))
    profile["searches"] = [
        s for s in profile.get("searches", []) if s.get("id") != search_id
    ]
    if len(profile["searches"]) == before:
        return False
    _save_profile(user_id, profile)
    return True


def store_uploaded_file(file_storage, user_upload_dir: str, original_filename: str) -> tuple[str, str]:
    """Save PDF to user folder. Returns (stored_filename, full_path)."""
    os.makedirs(user_upload_dir, exist_ok=True)
    safe = re.sub(r"[^\w.\-]", "_", original_filename or "resume.pdf")
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    stored = f"{uuid.uuid4().hex[:12]}_{safe}"
    full_path = os.path.join(user_upload_dir, stored)
    file_storage.save(full_path)
    return stored, full_path


def _db():
    from utils import db_history

    return db_history


def save_resume_record(user_id: str, stored_filename: str, original_filename: str) -> dict:
    if use_database():
        return _db().save_resume_record(user_id, stored_filename, original_filename)
    return _file_save_resume_record(user_id, stored_filename, original_filename)


def log_job_search(user_id: str, jd_text: str, *, resume_id: str | None = None, tool: str = "resume_optimizer", extra: dict | None = None) -> dict:
    if use_database():
        return _db().log_job_search(user_id, jd_text, resume_id=resume_id, tool=tool, extra=extra)
    return _file_log_job_search(user_id, jd_text, resume_id=resume_id, tool=tool, extra=extra)


def update_job_search(user_id: str, search_id: str, **fields) -> dict | None:
    if use_database():
        return _db().update_job_search(user_id, search_id, **fields)
    return _file_update_job_search(user_id, search_id, **fields)


def log_coach_query(user_id: str, message: str) -> None:
    if use_database():
        return _db().log_coach_query(user_id, message)
    return _file_log_coach_query(user_id, message)


def get_user_history(user_id: str) -> dict:
    if use_database():
        return _db().get_user_history(user_id)
    return _file_get_user_history(user_id)


def find_resume(user_id: str, resume_id: str) -> dict | None:
    if use_database():
        return _db().find_resume(user_id, resume_id)
    return _file_find_resume(user_id, resume_id)


def find_search(user_id: str, search_id: str) -> dict | None:
    if use_database():
        return _db().find_search(user_id, search_id)
    return _file_find_search(user_id, search_id)


def delete_resume(user_id: str, resume_id: str, user_upload_dir: str) -> bool:
    if use_database():
        return _db().delete_resume(user_id, resume_id, user_upload_dir)
    return _file_delete_resume(user_id, resume_id, user_upload_dir)


def delete_search(user_id: str, search_id: str) -> bool:
    if use_database():
        return _db().delete_search(user_id, search_id)
    return _file_delete_search(user_id, search_id)

