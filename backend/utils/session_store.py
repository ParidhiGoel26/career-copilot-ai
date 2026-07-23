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

from flask import session


def _base_dir(upload_folder: str) -> Path:
    path = Path(upload_folder) / "session_blobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_store_id() -> str:
    store_id = session.get("_store_id")
    if not store_id:
        store_id = uuid.uuid4().hex
        session["_store_id"] = store_id
        session.modified = True
    return store_id


def _blob_path(upload_folder: str, name: str, ext: str) -> Path:
    store_dir = _base_dir(upload_folder) / get_store_id()
    store_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in ("_", "-"))
    return store_dir / f"{safe}.{ext}"


def save_json(upload_folder: str, name: str, data) -> None:
    path = _blob_path(upload_folder, name, "json")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_json(upload_folder: str, name: str, default=None):
    path = _blob_path(upload_folder, name, "json")
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_text(upload_folder: str, name: str, text: str) -> None:
    path = _blob_path(upload_folder, name, "txt")
    path.write_text(text or "", encoding="utf-8")


def load_text(upload_folder: str, name: str, default: str = "") -> str:
    path = _blob_path(upload_folder, name, "txt")
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def delete_blob(upload_folder: str, name: str) -> None:
    for ext in ("json", "txt"):
        path = _blob_path(upload_folder, name, ext)
        if path.exists():
            try:
                os.remove(path)
            except OSError:
                pass
