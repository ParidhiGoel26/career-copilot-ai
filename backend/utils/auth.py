"""JWT authentication with JSON file store or SQLAlchemy (USE_DATABASE flag)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt
from flask import g, jsonify, redirect, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from utils.feature_flags import use_database

USERS_FILE = Path(__file__).resolve().parent.parent / "data" / "users.json"
TOKEN_COOKIE = "access_token"
TOKEN_HOURS = 24


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET_KEY") or os.getenv("FLASK_SECRET_KEY", "change-me-in-production")


def _db_users():
    from utils import db_users

    return db_users


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {"users": []}
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"users": []}


def _save_users(data: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def find_user_by_email(email: str):
    if use_database():
        return _db_users().find_user_by_email(email)
    email = (email or "").strip().lower()
    for user in _load_users().get("users", []):
        if user.get("email") == email:
            return user
    return None


def find_user_by_id(user_id: str):
    if use_database():
        return _db_users().find_user_by_id(user_id)
    for user in _load_users().get("users", []):
        if user.get("id") == user_id:
            return user
    return None


def create_user(email: str, password: str, name: str = "") -> dict:
    if use_database():
        return _db_users().create_user(email, password, name)

    email = (email or "").strip().lower()
    if not email or not password:
        raise ValueError("Email and password are required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if find_user_by_email(email):
        raise ValueError("An account with this email already exists.")

    user = {
        "id": uuid.uuid4().hex,
        "email": email,
        "name": (name or email.split("@")[0]).strip(),
        "password_hash": generate_password_hash(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    data = _load_users()
    data.setdefault("users", []).append(user)
    _save_users(data)
    return _public_user(user)


def authenticate_user(email: str, password: str):
    if use_database():
        return _db_users().authenticate_user(email, password)
    user = find_user_by_email(email)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return None
    return _public_user(user)


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", user["email"]),
    }


def create_access_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


def verify_access_token(token: str | None):
    if not token:
        return None
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        user = find_user_by_id(payload.get("sub", ""))
        if not user:
            return None
        return _public_user(user)
    except jwt.PyJWTError:
        return None


def get_token_from_request():
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return request.cookies.get(TOKEN_COOKIE)


def ensure_default_user():
    """Create the default admin when no users exist (flag-aware; no blind init_db)."""
    if use_database():
        _db_users().ensure_default_user()
        return
    if _load_users().get("users"):
        return
    email = os.getenv("DEFAULT_USER_EMAIL", "admin@careerai.local")
    password = os.getenv("DEFAULT_USER_PASSWORD", "admin123")
    create_user(email, password, name="Admin")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = verify_access_token(get_token_from_request())
        if not user:
            if request.is_json or request.path.startswith("/auth/"):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("login", next=request.url))
        g.current_user = user
        return view(*args, **kwargs)

    return wrapped


PUBLIC_ENDPOINTS = frozenset({
    "health",
    "ready",
    "metrics",
    "static",
    "login",
    "register",
    "auth_login",
    "auth_register",
})


def register_auth_hooks(app):
    @app.before_request
    def load_current_user():
        g.current_user = verify_access_token(get_token_from_request())

    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if g.get("current_user"):
            return None
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": "Unauthorized. Please log in."}), 401
        return redirect(url_for("login", next=request.url))
