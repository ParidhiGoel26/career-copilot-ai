"""Database-backed user repository (Slice 2).

Mirrors the public shapes used by utils.auth so Slice 3 can swap storage
behind a flag without changing route code much.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from utils.db import get_session
from utils.models import User


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name or user.email,
    }


def _to_dict(user: User) -> dict:
    created = user.created_at.isoformat() if user.created_at else None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "password_hash": user.password_hash,
        "created_at": created,
    }


def find_user_by_email(email: str):
    email = (email or "").strip().lower()
    if not email:
        return None
    session = get_session()
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        return _to_dict(user) if user else None
    finally:
        session.close()


def find_user_by_id(user_id: str):
    if not user_id:
        return None
    session = get_session()
    try:
        user = session.get(User, user_id)
        return _to_dict(user) if user else None
    finally:
        session.close()


def create_user(email: str, password: str, name: str = "") -> dict:
    email = (email or "").strip().lower()
    if not email or not password:
        raise ValueError("Email and password are required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")

    session = get_session()
    try:
        if session.query(User).filter_by(email=email).one_or_none():
            raise ValueError("An account with this email already exists.")

        user = User(
            email=email,
            name=(name or email.split("@")[0]).strip(),
            password_hash=generate_password_hash(password),
            created_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return _public_user(user)
    except IntegrityError as exc:
        session.rollback()
        raise ValueError("An account with this email already exists.") from exc
    finally:
        session.close()


def authenticate_user(email: str, password: str):
    user = find_user_by_email(email)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return None
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", user["email"]),
    }


def ensure_default_user() -> None:
    """Create the default admin user if the users table is empty.

    Does not re-init the engine, so tests can keep an in-memory DB.
    """
    session = get_session()
    try:
        if session.query(User).count() > 0:
            return
    finally:
        session.close()

    email = os.getenv("DEFAULT_USER_EMAIL", "admin@careerai.local")
    password = os.getenv("DEFAULT_USER_PASSWORD", "admin123")
    create_user(email, password, name="Admin")


def count_users() -> int:
    session = get_session()
    try:
        return session.query(User).count()
    finally:
        session.close()
