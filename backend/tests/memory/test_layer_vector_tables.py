from __future__ import annotations

import sqlite3

import pytest


def _has_virtual_table_with_prefix(db_path: str, prefix: str) -> bool:
    with sqlite3.connect(db_path) as db:
        definitions = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name LIKE ?", (f"{prefix}%",)
        ).fetchall()
    return any(
        "CREATE VIRTUAL TABLE" in str(row[0]).upper() and "USING VEC0" in str(row[0]).upper()
        for row in definitions
    )


class _FakeEmbeddingService:
    async def embed_text(self, text: str):
        from magi.memory.embedding.embedding_service import EmbeddingResult

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
async def test_memory_layers_create_sqlite_vec_virtual_tables_on_insert(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore

    embedding_service = _FakeEmbeddingService()
    l1_db = tmp_path / "l1_events.db"
    shared_db = tmp_path / "memory.db"

    l1_store = L1EventStore(
        db_path=str(l1_db), embedding_service=embedding_service, async_embeddings=False
    )
    l3_store = L3SummaryStore(
        db_path=str(shared_db), embedding_service=embedding_service, async_embeddings=False
    )
    l4_store = L4ProceduralMemoryStore(
        db_path=str(shared_db), embedding_service=embedding_service, async_embeddings=False
    )

    try:
        await l1_store.initialize()
        await l3_store.initialize()
        await l4_store.initialize()

        event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "stress journal"},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-1",
                event_id="evt-1",
            ),
        )
        await l1_store.store(event)
        await l3_store._store_summary(
            {
                "summary_id": "summary-1",
                "summary_type": "temporal",
                "summary_category": "day",
                "period_start": 1.0,
                "period_end": 2.0,
                "content": "stress day summary",
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
        await l4_store.record_memory_event(
            normalize_runtime_event(
                Event(
                    type=EventTypes.ACTION_EXECUTED,
                    data={
                        "action_type": "browser.open",
                        "success": True,
                        "execution_time": 0.2,
                        "optimized_prompt": "browser playbook",
                    },
                    source="runtime",
                    level=EventLevel.INFO,
                    correlation_id="corr-2",
                    event_id="evt-2",
                ),
            )
        )

        from magi.memory.embedding.embedding_service import EmbeddingResult

        for store, registry, expected_vector in [
            (l1_store, "l1_event_chunk_vectors", [1.0, 0.0, 0.0, 0.0]),
            (l3_store, "l3_summary_chunk_vectors", [1.0, 0.0, 0.0, 0.0]),
            (l4_store, "l4_skill_chunk_vectors", [0.0, 0.0, 1.0, 0.0]),
        ]:
            with sqlite3.connect(store.db_path) as db:
                [row] = db.execute(f"SELECT chunk_id FROM {registry}").fetchall()
            chunk_id = row[0]
            vectors = await store._vector_index.get_vectors(entity_ids=[chunk_id])
            assert vectors == {chunk_id: expected_vector}
            hits = await store._vector_index.search(
                embedding=EmbeddingResult(
                    model_name="test-embedding", dimension=4, vector=expected_vector
                ),
                limit=10,
            )
            assert [(hit.entity_id, hit.distance) for hit in hits] == [(chunk_id, 0.0)]
        assert _has_virtual_table_with_prefix(str(l1_db), "l1_event_vec_")
        assert _has_virtual_table_with_prefix(str(shared_db), "l3_summary_chunk_vec_")
        assert _has_virtual_table_with_prefix(str(shared_db), "l4_skill_chunk_vec_")
    finally:
        await l1_store.shutdown()
        await l3_store.shutdown()
        await l4_store.shutdown()
