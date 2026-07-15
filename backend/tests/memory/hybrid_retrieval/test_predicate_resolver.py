"""Embedding-primary predicate resolver + degrade (RFC #65 P1)."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.models import L2Conditions
from magi.memory.hybrid_retrieval.predicate_resolver import resolve_predicates
from magi.memory.hybrid_retrieval.predicate_label_embeddings import reset_predicate_label_cache


class _FakeEmbeddingResult:
    def __init__(self, vector):
        self.vector = vector
        self.model_identity = "fake-v1"


class _FakeEmbeddingService:
    model_identity = "fake-v1"

    def _vec(self, text: str):
        t = text.lower()
        return [
            1.0 if ("listen" in t or "heard" in t) else 0.0,
            1.0 if ("like" in t or "fond" in t or "enjoy" in t) else 0.0,
            1.0 if ("work" in t or "employ" in t) else 0.0,
            1.0 if ("know" in t or "acquaint" in t) else 0.0,
        ]

    async def embed_text(self, text: str):
        return _FakeEmbeddingResult(self._vec(text))

    async def embed_texts(self, texts):
        return [_FakeEmbeddingResult(self._vec(t)) for t in texts]


@pytest.fixture(autouse=True)
def _clear_cache():
    reset_predicate_label_cache()
    yield
    reset_predicate_label_cache()


@pytest.mark.asyncio
async def test_listening_resolves_to_listened():
    c = L2Conditions(relation_intent="listening to / consuming media")
    await resolve_predicates(c, embedding_service=_FakeEmbeddingService())
    assert c.predicates is not None and "LISTENED" in c.predicates
    assert c.predicate_source == "embedding"
    assert c.predicate_family == "activity"


@pytest.mark.asyncio
async def test_likes_resolves_to_likes():
    c = L2Conditions(relation_intent="likes / is fond of")
    await resolve_predicates(c, embedding_service=_FakeEmbeddingService())
    assert c.predicates is not None and "LIKES" in c.predicates
    assert c.predicate_source == "embedding"


@pytest.mark.asyncio
async def test_no_match_degrades_to_keyword_when_no_family():
    c = L2Conditions(relation_intent="xyzzy nonsense")
    await resolve_predicates(c, embedding_service=_FakeEmbeddingService())
    assert c.predicates is None
    assert c.predicate_source == "keyword_fallback"


@pytest.mark.asyncio
async def test_no_match_degrades_to_llm_family_when_family_present():
    c = L2Conditions(relation_intent="xyzzy nonsense", predicate_family="preference")
    await resolve_predicates(c, embedding_service=_FakeEmbeddingService())
    assert c.predicates is None
    assert c.predicate_source == "llm_family"


@pytest.mark.asyncio
async def test_explicit_predicates_not_overridden():
    c = L2Conditions(predicates=["LIKES"], relation_intent="listening to media")
    await resolve_predicates(c, embedding_service=_FakeEmbeddingService())
    assert c.predicates == ["LIKES"]
    assert c.predicate_source == "explicit"


@pytest.mark.asyncio
async def test_no_embedding_service_degrades():
    c = L2Conditions(relation_intent="listening to media")
    await resolve_predicates(c, embedding_service=None)
    assert c.predicates is None
    assert c.predicate_source == "keyword_fallback"


@pytest.mark.asyncio
async def test_end_to_end_listening_populates_predicates_via_handler():
    """execute() runs resolve_predicates before grounding → predicates has LISTENED."""
    from unittest.mock import AsyncMock
    from magi.memory.hybrid_retrieval.l2_handler import L2Handler

    store = AsyncMock()
    store.batch_get_relationships = AsyncMock(return_value={})
    store.batch_list_current_relationships = AsyncMock(return_value={})
    store.get_relationships = AsyncMock(return_value=[])
    store.search_edges_by_embedding = AsyncMock(return_value=[])
    store.list_episodes = AsyncMock(return_value=[])
    store.search_episodes_fts = AsyncMock(return_value=[])

    handler = L2Handler(store, embedding_service=_FakeEmbeddingService())
    conditions = L2Conditions(
        content_query="songs I'm listening to",
        relation_intent="listening to / consuming media",
        include_assertions=False,
        include_tom_snapshot=False,
    )
    await handler.execute(conditions, user_id="u1")
    assert conditions.predicates is not None and "LISTENED" in conditions.predicates
    assert conditions.predicate_source == "embedding"
