"""Migrate JSON user/auth + activity files into the SQLAlchemy DB (Slice 5).

Idempotent: existing rows (same primary key or email) are skipped.
Does not delete or modify source JSON files.

Usage:
  cd backend
  python -m utils.migrate_to_db
  # then set USE_DATABASE=true in .env
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from utils.db import get_session, init_db
from utils.models import CoachQuery, JobSearch, Resume, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_USERS = BACKEND_DIR / "data" / "users.json"
DEFAULT_ACTIVITY = BACKEND_DIR / "data" / "user_activity"


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def migrate_users(users_file: Path, session) -> dict:
    stats = {"users_added": 0, "users_skipped": 0}
    data = _load_json(users_file) or {"users": []}
    for raw in data.get("users", []):
        email = (raw.get("email") or "").strip().lower()
        uid = raw.get("id")
        if not email or not uid or not raw.get("password_hash"):
            stats["users_skipped"] += 1
            continue
        existing = session.get(User, uid) or session.query(User).filter_by(email=email).one_or_none()
        if existing:
            stats["users_skipped"] += 1
            continue
        session.add(
            User(
                id=uid,
                email=email,
                name=(raw.get("name") or email.split("@")[0]).strip(),
                password_hash=raw["password_hash"],
                created_at=_parse_dt(raw.get("created_at")) or _utcnow(),
            )
        )
        stats["users_added"] += 1
    session.commit()
    return stats


def migrate_activity(activity_dir: Path, session) -> dict:
    stats = {
        "profiles": 0,
        "resumes_added": 0,
        "resumes_skipped": 0,
        "searches_added": 0,
        "searches_skipped": 0,
        "coach_added": 0,
        "coach_skipped": 0,
        "orphan_profiles": 0,
    }
    if not activity_dir.exists():
        return stats

    for path in sorted(activity_dir.glob("*.json")):
        data = _load_json(path)
        if not data:
            continue
        user_id = data.get("user_id") or path.stem
        user = session.get(User, user_id)
        if not user:
            stats["orphan_profiles"] += 1
            continue
        stats["profiles"] += 1

        for raw in data.get("resumes", []):
            rid = raw.get("id")
            if not rid or session.get(Resume, rid):
                stats["resumes_skipped"] += 1
                continue
            session.add(
                Resume(
                    id=rid,
                    user_id=user_id,
                    stored_filename=raw.get("stored_filename") or "",
                    original_filename=raw.get("original_filename") or "",
                    uploaded_at=_parse_dt(raw.get("uploaded_at")) or _utcnow(),
                )
            )
            stats["resumes_added"] += 1

        session.flush()

        for raw in data.get("searches", []):
            sid = raw.get("id")
            if not sid or session.get(JobSearch, sid):
                stats["searches_skipped"] += 1
                continue
            resume_id = raw.get("resume_id")
            if resume_id and session.get(Resume, resume_id) is None:
                resume_id = None
            session.add(
                JobSearch(
                    id=sid,
                    user_id=user_id,
                    resume_id=resume_id,
                    tool=raw.get("tool") or "resume_optimizer",
                    title=raw.get("title") or "Untitled search",
                    jd_text=raw.get("jd_text") or "",
                    ats_score=raw.get("ats_score"),
                    readiness_score=raw.get("readiness_score"),
                    created_at=_parse_dt(raw.get("created_at")) or _utcnow(),
                    updated_at=_parse_dt(raw.get("updated_at")),
                )
            )
            stats["searches_added"] += 1

        for raw in data.get("coach_queries", []):
            cid = raw.get("id")
            if not cid or session.get(CoachQuery, cid):
                stats["coach_skipped"] += 1
                continue
            session.add(
                CoachQuery(
                    id=cid,
                    user_id=user_id,
                    message=(raw.get("message") or "")[:500],
                    created_at=_parse_dt(raw.get("created_at")) or _utcnow(),
                )
            )
            stats["coach_added"] += 1

        session.commit()

    return stats


def run_migration(
    users_file: Path | None = None,
    activity_dir: Path | None = None,
    database_url: str | None = None,
) -> dict:
    init_db(database_url)
    session = get_session()
    try:
        user_stats = migrate_users(users_file or DEFAULT_USERS, session)
        activity_stats = migrate_activity(activity_dir or DEFAULT_ACTIVITY, session)
        return {**user_stats, **activity_stats}
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    users = DEFAULT_USERS
    activity = DEFAULT_ACTIVITY
    db_url = None
    # Optional: --users path --activity path --database-url url
    i = 0
    while i < len(argv):
        if argv[i] == "--users" and i + 1 < len(argv):
            users = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--activity" and i + 1 < len(argv):
            activity = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--database-url" and i + 1 < len(argv):
            db_url = argv[i + 1]
            i += 2
        else:
            print(f"Unknown arg: {argv[i]}", file=sys.stderr)
            return 2

    stats = run_migration(users_file=users, activity_dir=activity, database_url=db_url)
    print("Migration complete:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print("\nNext: set USE_DATABASE=true in .env and restart the app.")
    print("JSON source files were left untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
