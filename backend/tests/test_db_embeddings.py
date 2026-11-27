"""Persisted embedding chunk tests (Week 2 Slice 2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.db import reset_db_for_tests
from utils import db_embeddings, db_users
from utils.embeddings import HashingEmbedder
from utils.feature_flags import persist_embeddings
from utils.knowledge_base import build_knowledge_base
from utils.rag import UserKnowledgeBase


DOC = """
Software engineer skilled in Flask, SQLAlchemy, and Docker.
Built an embedding RAG pipeline for career coaching.
"""


@pytest.fixture()
def db_user(monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("USE_EMBEDDINGS", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("EMBEDDING_DIM", "64")
    reset_db_for_tests("sqlite:///:memory:")
    user = db_users.create_user("embed@example.com", "secret12", name="Embed")
    yield user


def test_persist_embeddings_flag(db_user):
    assert persist_embeddings() is True


def test_index_then_cache_hit(db_user):
    emb = HashingEmbedder(dim=64)
    uid = db_user["id"]
    chunks1 = db_embeddings.load_or_index(uid, "resume", DOC, "Resume", emb)
    assert len(chunks1) >= 1
    assert all(c.get("embedding") for c in chunks1)
    assert db_embeddings.count_chunks(uid) == len(chunks1)

    chunks2 = db_embeddings.load_or_index(uid, "resume", DOC, "Resume", emb)
    assert len(chunks2) == len(chunks1)
    # Same vectors from cache
    assert chunks2[0]["embedding"] == chunks1[0]["embedding"]


def test_content_change_reindexes(db_user):
    emb = HashingEmbedder(dim=64)
    uid = db_user["id"]
    db_embeddings.load_or_index(uid, "resume", DOC, "Resume", emb)
    updated = DOC + "\nAlso knows Kubernetes and Postgres."
    chunks = db_embeddings.load_or_index(uid, "resume", updated, "Resume", emb)
    assert any("Kubernetes" in c["text"] for c in chunks)


def test_kb_uses_cache_on_second_build(db_user, monkeypatch):
    monkeypatch.setattr("utils.knowledge_base.load_text", lambda *a, **k: "")
    uid = db_user["id"]
    session = {"jd": DOC}
    kb1 = build_knowledge_base(session, upload_folder="/tmp", user_id=uid)
    assert kb1.chunks
    assert all(c.get("embedding") for c in kb1.chunks)
    count_after_first = db_embeddings.count_chunks(uid)
    assert count_after_first > 0

    # Second build should hit cache (same content_hash) — count unchanged
    kb2 = build_knowledge_base(session, upload_folder="/tmp", user_id=uid)
    assert db_embeddings.count_chunks(uid) == count_after_first
    hits = kb2.retrieve("Flask Docker embeddings", top_k=2)
    assert hits
    assert hits[0]["source"] == "job_description"


def test_no_persist_when_embeddings_off(monkeypatch):
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("USE_EMBEDDINGS", "false")
    monkeypatch.setattr("utils.knowledge_base.load_text", lambda *a, **k: "")
    reset_db_for_tests("sqlite:///:memory:")
    user = db_users.create_user("nof@example.com", "secret12")
    assert persist_embeddings() is False
    kb = build_knowledge_base({"jd": DOC}, "/tmp", user_id=user["id"])
    assert kb.chunks
    assert "embedding" not in kb.chunks[0]
    assert db_embeddings.count_chunks(user["id"]) == 0
