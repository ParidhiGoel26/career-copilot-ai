"""Embedding RAG switch tests (Week 2 Slice 1)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from utils.embeddings import HashingEmbedder, cosine_similarity, get_embedder
from utils.feature_flags import use_embeddings
from utils.rag import UserKnowledgeBase


RESUME = """
Paridhi Goel
Software Engineer

EXPERIENCE
Built Flask APIs and SQLAlchemy data models for a career coaching product.
Deployed services with Docker and wrote pytest coverage for auth flows.

PROJECTS
Resume Optimizer — AI resume tailoring tool using Groq LLMs
"""

JD = """
We need a backend engineer strong in Python, Flask, SQLAlchemy, and Docker.
Experience with RAG systems and embeddings is a plus.
"""


def test_cosine_similarity_basics():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([], [1]) == 0.0


def test_hashing_embedder_is_deterministic():
    emb = HashingEmbedder(dim=64)
    a = emb.embed_query("Flask SQLAlchemy Docker")
    b = emb.embed_query("Flask SQLAlchemy Docker")
    assert a == b
    assert len(a) == 64
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


def test_tfidf_mode_default(monkeypatch):
    monkeypatch.setenv("USE_EMBEDDINGS", "false")
    assert use_embeddings() is False
    kb = UserKnowledgeBase()
    kb.add_document("resume", RESUME, "Resume")
    kb.add_document("job_description", JD, "JD")
    hits = kb.retrieve("Docker pytest auth", top_k=3)
    assert hits
    assert "embedding" not in kb.chunks[0]
    assert any("Docker" in h["text"] or "pytest" in h["text"] for h in hits)


def test_embedding_mode_ranks_relevant_chunk(monkeypatch):
    monkeypatch.setenv("USE_EMBEDDINGS", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("EMBEDDING_DIM", "128")
    assert use_embeddings() is True

    kb = UserKnowledgeBase(embedder=HashingEmbedder(dim=128))
    kb.add_document("resume", RESUME, "Resume")
    kb.add_document(
        "noise",
        "Cooking recipes: pasta, tomatoes, basil, olive oil, garlic bread.",
        "Noise",
    )
    hits = kb.retrieve("Docker and Flask backend experience", top_k=2)
    assert hits
    assert all("embedding" in c for c in kb.chunks)
    # Top hit should come from resume, not cooking noise
    assert hits[0]["source"] == "resume"
    assert hits[0]["score"] > 0


def test_get_embedder_defaults_to_hashing(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    emb = get_embedder()
    assert isinstance(emb, HashingEmbedder)


def test_coach_retrieve_shape_unchanged(monkeypatch):
    """career_coach expects list of {label, text, score, source}."""
    monkeypatch.setenv("USE_EMBEDDINGS", "true")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    kb = UserKnowledgeBase(embedder=HashingEmbedder(dim=64))
    kb.add_document("resume", RESUME, "Uploaded Resume")
    hits = kb.retrieve("SQLAlchemy models", top_k=3)
    assert hits
    for h in hits:
        assert "label" in h and "text" in h and "score" in h and "source" in h
