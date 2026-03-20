from __future__ import annotations

import pytest


class FakeEmbeddingService:
    async def embed_text(self, text: str):
        from magi.memory.embedding_service import EmbeddingResult

        lowered = text.lower()
        vector = [0.0, 0.0, 0.0, 0.0]
        if "stress" in lowered:
            vector[0] = 1.0
        if "calm" in lowered:
            vector[1] = 1.0
        if "browser" in lowered:
            vector[2] = 1.0
        if not any(vector):
            vector[3] = 1.0
        return EmbeddingResult(model_name="test-embedding", dimension=4, vector=vector)


@pytest.mark.asyncio
async def test_l1_store_uses_sqlite_vec_for_semantic_search(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l1.event_store import L1EventStore

    store = L1EventStore(db_path=str(tmp_path / "l1.db"), embedding_service=FakeEmbeddingService(), async_embeddings=False)
    try:
        await store.initialize()

        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I feel stress at work",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-1",
                ),
                event_id="evt-stress",
            )
        )
        await store.store(
            normalize_runtime_event(
                Event(
                    type=EventTypes.USER_MESSAGE,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "I feel calm today",
                        "author_type": "user",
                        "content_type": "text",
                    },
                    source="chat",
                    level=EventLevel.INFO,
                    correlation_id="corr-2",
                ),
                event_id="evt-calm",
            )
        )

        results = await store.search_events(query="stress", user_id="u1", limit=2)

        assert results
        assert results[0]["event_id"] == "evt-stress"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l3_store_uses_sqlite_vec_for_semantic_search(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    store = L3SummaryStore(db_path=str(tmp_path / "memory.db"), embedding_service=FakeEmbeddingService(), async_embeddings=False)
    try:
        await store.initialize()

        await store._store_summary(
            {
                "summary_id": "summary-stress",
                "summary_type": "temporal",
                "summary_category": "day",
                "period_start": 1.0,
                "period_end": 2.0,
                "content": "stress summary",
                "key_topics": [],
                "key_entities": [],
                "sentiment_summary": None,
                "source_event_ids": ["evt-1"],
                "source_event_count": 1,
                "importance_aggregate": 0.8,
                "event_type_distribution": {},
                "generated_by_model": "rule-summary",
                "generation_prompt": None,
                "generation_reason": "temporal:day",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )
        await store._store_summary(
            {
                "summary_id": "summary-calm",
                "summary_type": "temporal",
                "summary_category": "day",
                "period_start": 1.0,
                "period_end": 2.0,
                "content": "calm summary",
                "key_topics": [],
                "key_entities": [],
                "sentiment_summary": None,
                "source_event_ids": ["evt-2"],
                "source_event_count": 1,
                "importance_aggregate": 0.7,
                "event_type_distribution": {},
                "generated_by_model": "rule-summary",
                "generation_prompt": None,
                "generation_reason": "temporal:day",
                "created_at": 1.0,
                "updated_at": 1.0,
            }
        )

        results = await store.search_summaries(query="stress", limit=2)

        assert results
        assert results[0]["summary_id"] == "summary-stress"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_l4_store_uses_sqlite_vec_for_semantic_search(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    store = L4ProceduralMemoryStore(db_path=str(tmp_path / "memory.db"), embedding_service=FakeEmbeddingService(), async_embeddings=False)
    try:
        await store.initialize()

        await store.record_memory_event(
            normalize_runtime_event(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={"action_type": "browser.open", "success": True, "execution_time": 0.3, "optimized_prompt": "browser stress workflow"},
                    source="runtime",
                    level=EventLevel.INFO,
                    correlation_id="corr-1",
                ),
                event_id="evt-1",
            )
        )
        await store.record_memory_event(
            normalize_runtime_event(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={"action_type": "calendar.create", "success": True, "execution_time": 0.2, "optimized_prompt": "calm calendar workflow"},
                    source="runtime",
                    level=EventLevel.INFO,
                    correlation_id="corr-2",
                ),
                event_id="evt-2",
            )
        )

        results = await store.query_strategies(query="browser stress", limit=2)

        assert results
        assert results[0]["skill_name"] == "browser.open"
    finally:
        await store.shutdown()
