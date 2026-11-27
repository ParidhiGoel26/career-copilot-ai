"""Persist / reload RAG chunk embeddings (Week 2 Slice 2).

Only used when persist_embeddings() is true (USE_DATABASE + USE_EMBEDDINGS).
Stores vectors as JSON float lists so SQLite works without pgvector.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from utils.db import get_session
from utils.models import KnowledgeChunk
from utils.rag import _chunk_text


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _provider_name() -> str:
    return (os.getenv("EMBEDDING_PROVIDER") or "hashing").strip().lower()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_cached_chunks(user_id: str, source: str, text: str) -> list[dict] | None:
    """Return cached chunks if content_hash matches; else None."""
    if not user_id or not source:
        return None
    digest = content_hash(text)
    provider = _provider_name()
    session = get_session()
    try:
        rows = (
            session.query(KnowledgeChunk)
            .filter_by(user_id=user_id, source=source, content_hash=digest, provider=provider)
            .order_by(KnowledgeChunk.chunk_index.asc())
            .all()
        )
        if not rows:
            return None
        return [
            {
                "id": row.chunk_index,
                "source": row.source,
                "text": row.text,
                "embedding": json.loads(row.embedding_json or "[]"),
                "label": row.label,
            }
            for row in rows
        ]
    finally:
        session.close()


def replace_document_chunks(
    user_id: str,
    source: str,
    text: str,
    label: str,
    embedder,
) -> list[dict]:
    """Chunk + embed + replace stored rows for this user/source. Returns chunk dicts."""
    digest = content_hash(text)
    provider = _provider_name()
    raw_chunks = _chunk_text(str(text), source)
    if not raw_chunks:
        _delete_source(user_id, source)
        return []

    vectors = embedder.embed_documents([c["text"] for c in raw_chunks])
    chunks = []
    for idx, (chunk, vector) in enumerate(zip(raw_chunks, vectors)):
        chunks.append(
            {
                "id": idx,
                "source": source,
                "text": chunk["text"],
                "embedding": vector,
                "label": label or source,
            }
        )

    session = get_session()
    try:
        session.query(KnowledgeChunk).filter_by(user_id=user_id, source=source).delete()
        for chunk in chunks:
            session.add(
                KnowledgeChunk(
                    user_id=user_id,
                    source=source,
                    label=label or source,
                    chunk_index=int(chunk["id"]),
                    text=chunk["text"],
                    embedding_json=json.dumps(chunk["embedding"]),
                    content_hash=digest,
                    provider=provider,
                    created_at=_utcnow(),
                )
            )
        session.commit()
    finally:
        session.close()
    return chunks


def load_or_index(user_id: str, source: str, text: str, label: str, embedder) -> list[dict]:
    """Use cache when content unchanged; otherwise re-index."""
    cached = load_cached_chunks(user_id, source, text)
    if cached is not None:
        return cached
    return replace_document_chunks(user_id, source, text, label, embedder)


def _delete_source(user_id: str, source: str) -> None:
    session = get_session()
    try:
        session.query(KnowledgeChunk).filter_by(user_id=user_id, source=source).delete()
        session.commit()
    finally:
        session.close()


def count_chunks(user_id: str | None = None) -> int:
    session = get_session()
    try:
        q = session.query(KnowledgeChunk)
        if user_id:
            q = q.filter_by(user_id=user_id)
        return q.count()
    finally:
        session.close()
