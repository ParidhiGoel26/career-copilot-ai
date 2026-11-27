"""Feature flags for gradual migrations."""

from __future__ import annotations

import os


def _flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes")


def use_database() -> bool:
    """When true, prefer SQLAlchemy repositories over JSON/file stores.

    Default is False so the live app stays on the current file-based path
    until Slice 3/4 explicitly flip the switch.
    """
    return _flag("USE_DATABASE")


def use_embeddings() -> bool:
    """When true, RAG retrieve() uses embedding cosine similarity.

    Default False keeps the existing TF-IDF keyword scorer.
    """
    return _flag("USE_EMBEDDINGS")


def persist_embeddings() -> bool:
    """Persist/load chunk vectors in DB when both DB + embeddings are on.

    Avoids re-embedding the same document on every coach request.
    """
    return use_database() and use_embeddings()


def use_async_jobs() -> bool:
    """When true, long LLM routes return 202 + job_id and run in a thread pool.

    Default False keeps synchronous request/response behavior.
    """
    return _flag("USE_ASYNC_JOBS")
