"""Predicate-label embedding cache + match pool (RFC #65 P1)."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.predicate_label_embeddings import (
    get_predicate_label_embeddings,
    match_pool_canonicals,
    reset_predicate_label_cache,
)


class _FakeEmbeddingResult:
    def __init__(self, vector, model_identity="fake-v1"):
        self.vector = vector
        self.model_identity = model_identity


class _FakeEmbeddingService:
    """Deterministic keyword→basis-vector embedder for tests."""

    model_identity = "fake-v1"

    def __init__(self):
        self.embed_texts_calls = 0

    def _vec(self, text: str):
        t = text.lower()
        # axes: [listen, like, work, know]
        return [
            1.0 if ("listen" in t or "heard" in t) else 0.0,
            1.0 if ("like" in t or "fond" in t or "enjoy" in t) else 0.0,
            1.0 if ("work" in t or "employ" in t) else 0.0,
            1.0 if ("know" in t or "acquaint" in t) else 0.0,
        ]

    async def embed_text(self, text: str):
        return _FakeEmbeddingResult(self._vec(text))

    async def embed_texts(self, texts):
        self.embed_texts_calls += 1
        return [_FakeEmbeddingResult(self._vec(t)) for t in texts]


def test_match_pool_includes_user_relations_excludes_topology():
    pool = set(match_pool_canonicals())
    assert {"LISTENED", "LIKES", "KNOWS", "WORKS_AT"} <= pool
    assert "PRESENCE_OF" not in pool
    assert "LOCATED_IN" not in pool
    assert "ON_PLATFORM" not in pool
    assert "REFERENCES" not in pool


@pytest.mark.asyncio
async def test_cache_reuses_each_model_without_cross_model_vector_contamination():
    class OtherModel(_FakeEmbeddingService):
        model_identity = "fake-v2"

        def _vec(self, text):
            return list(reversed(super()._vec(text)))

    first, second = _FakeEmbeddingService(), OtherModel()
    reset_predicate_label_cache()
    try:
        for service, listened, likes in [
            (first, [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]),
            (second, [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 0.0]),
            (first, [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]),
        ]:
            for _ in range(2):
                vectors = await get_predicate_label_embeddings(service)
                assert vectors["LISTENED"] == listened
                assert vectors["LIKES"] == likes
        assert (first.embed_texts_calls, second.embed_texts_calls) == (1, 1)
    finally:
        reset_predicate_label_cache()
