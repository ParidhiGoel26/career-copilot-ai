"""File-backed storage for large session payloads.

Flask's default cookie session is capped near 4KB by browsers. Large values
(optimized resume, interview state, chat history, documents) are stored as
JSON/text files under uploads/session_blobs/<store_id>/ and only a tiny
store_id stays in the cookie.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from flask import has_request_context, session


def _base_dir(upload_folder: str) -> Path:
    path = Path(upload_folder) / "session_blobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_store_id() -> str:
    """Return the request's store id (creates one in the cookie session).

    Outside a request (workers/tests) callers must pass store_id explicitly.
    """
    if not has_request_context():
        raise RuntimeError("store_id is required outside a request context")
    store_id = session.get("_store_id")
    if not store_id:
        store_id = uuid.uuid4().hex
        session["_store_id"] = store_id
        session.modified = True
    return store_id


def _blob_path(upload_folder: str, name: str, ext: str, store_id: str | None = None) -> Path:
    sid = store_id or get_store_id()
    store_dir = _base_dir(upload_folder) / "".join(
        c for c in sid if c.isalnum() or c in ("_", "-")
    )
    store_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-"))
    return store_dir / f"{safe}.{ext}"


def save_json(upload_folder: str, name: str, data, store_id: str | None = None) -> None:
    path = _blob_path(upload_folder, name, "json", store_id)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_json(upload_folder: str, name: str, default=None, store_id: str | None = None):
    path = _blob_path(upload_folder, name, "json", store_id)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_text(upload_folder: str, name: str, text: str, store_id: str | None = None) -> None:
    path = _blob_path(upload_folder, name, "txt", store_id)
    path.write_text(text or "", encoding="utf-8")


def load_text(upload_folder: str, name: str, default: str = "", store_id: str | None = None) -> str:
    path = _blob_path(upload_folder, name, "txt", store_id)
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def delete_blob(upload_folder: str, name: str, store_id: str | None = None) -> None:
    for ext in ("json", "txt"):
        path = _blob_path(upload_folder, name, ext, store_id)
        if path.exists():
            try:
                os.remove(path)
            except OSError:
                pass
