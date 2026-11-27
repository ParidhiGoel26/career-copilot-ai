"""Embedding providers for RAG retrieval (Week 2).

Default offline path: deterministic hashing embedder (no network, tests-friendly).
Optional API path: OpenAI-compatible embeddings when EMBEDDING_API_KEY is set.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z]{2,}\b", (text or "").lower())


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Signed feature-hashing embedder (offline, deterministic).

    Good enough for local demos/tests. Swap to ApiEmbedder for production quality.
    """

    def __init__(self, dim: int = 256):
        self.dim = max(32, int(dim))

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _tokenize(text)
        if not tokens:
            return vec
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class ApiEmbedder:
    """OpenAI-compatible embeddings (OpenAI, Azure, local gateways, etc.)."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ):
        from openai import OpenAI

        self.model = model or os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [t if t and t.strip() else " " for t in texts]
        resp = self._client.embeddings.create(model=self.model, input=cleaned)
        # Ensure order by index
        data = sorted(resp.data, key=lambda d: d.index)
        return [list(d.embedding) for d in data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text or " "])[0]


def get_embedder() -> Embedder:
    """Resolve embedder from env.

    EMBEDDING_PROVIDER=hashing|api  (default: hashing)
    For api: EMBEDDING_API_KEY (or OPENAI_API_KEY), optional EMBEDDING_BASE_URL / EMBEDDING_MODEL
    """
    provider = (os.getenv("EMBEDDING_PROVIDER") or "hashing").strip().lower()
    if provider == "api":
        key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if not key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=api requires EMBEDDING_API_KEY or OPENAI_API_KEY"
            )
        return ApiEmbedder(
            api_key=key,
            model=os.getenv("EMBEDDING_MODEL"),
            base_url=os.getenv("EMBEDDING_BASE_URL") or None,
        )
    dim = int(os.getenv("EMBEDDING_DIM", "256"))
    return HashingEmbedder(dim=dim)
