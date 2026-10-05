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
@pytest.mark.parametrize(
    "intent,predicate,family",
    [
        ("listening to / consuming media", "LISTENED", "activity"),
        ("likes / is fond of", "LIKES", "preference"),
    ],
)
async def test_semantic_predicate_resolution_preserves_relation_family(intent, predicate, family):
    conditions = L2Conditions(relation_intent=intent)
    await resolve_predicates(conditions, embedding_service=_FakeEmbeddingService())
    assert predicate in conditions.predicates
    assert conditions.predicate_source == "embedding"
    assert conditions.predicate_family == family


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
async def test_handler_uses_resolved_listening_predicate_to_select_persisted_facts(tmp_path):
    import time
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.hybrid_retrieval.l2_handler import L2Handler

    path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(path)
    store = L2CognitionStore(db_path=path)
    await store.initialize()
    ids = {}
    for predicate, target in [("LISTENED", "media:current-song"), ("LIKES", "media:liked-only")]:
        ids[predicate] = await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="person",
            predicate=predicate,
            object_id=target,
            object_type="media",
            evidence_event_ids=[f"event:{target}"],
            confidence=0.9,
            observed_at=time.time(),
            source_type="conversation",
        )
    handler = L2Handler(store, embedding_service=_FakeEmbeddingService())
    conditions = L2Conditions(
        content_query="songs I'm listening to",
        relation_intent="listening to / consuming media",
        subject_hint="self",
        include_assertions=False,
        include_tom_snapshot=False,
        include_episodes=False,
        include_experiences=False,
        allow_soft_edges=False,
    )
    result = await handler.execute(conditions, user_id="u1")
    assert [
        (row["triple_id"], row["predicate"], row["object_id"]) for row in result["relationships"]
    ] == [(ids["LISTENED"], "LISTENED", "media:current-song")]
    assert conditions.predicate_source == "embedding"
