from __future__ import annotations

import sqlite3

import pytest


def _has_table(db_path: str, table_name: str) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def _has_virtual_table_with_prefix(db_path: str, prefix: str) -> bool:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name LIKE ? LIMIT 1",
        (f"{prefix}%",),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


class _FakeEmbeddingService:
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
async def test_memory_layers_create_dedicated_vector_tables(tmp_path):
    from magi.memory.l1_event_store import L1EventStore
    from magi.memory.l3_summary_store import L3SummaryStore
    from magi.memory.l4_procedural_memory import L4ProceduralMemoryStore

    l1_db = tmp_path / "l1_events.db"
    l3_db = tmp_path / "l3_reflections.db"
    l4_db = tmp_path / "l4_procedural.db"

    embedding_service = _FakeEmbeddingService()
    l1_store = L1EventStore(db_path=str(l1_db), embedding_service=embedding_service, async_embeddings=False)
    l3_store = L3SummaryStore(db_path=str(l3_db), embedding_service=embedding_service, async_embeddings=False)
    l4_store = L4ProceduralMemoryStore(db_path=str(l4_db), embedding_service=embedding_service, async_embeddings=False)

    try:
        await l1_store.initialize()
        await l3_store.initialize()
        await l4_store.initialize()

        assert _has_table(str(l1_db), "l1_event_vectors")
        assert _has_table(str(l3_db), "l3_summary_vectors")
        assert _has_table(str(l4_db), "l4_skill_vectors")
    finally:
        await l1_store.shutdown()
        await l3_store.shutdown()
        await l4_store.shutdown()


@pytest.mark.asyncio
async def test_memory_layers_create_sqlite_vec_virtual_tables_on_insert(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l1_event_store import L1EventStore
    from magi.memory.l3_summary_store import L3SummaryStore
    from magi.memory.l4_procedural_memory import L4ProceduralMemoryStore

    embedding_service = _FakeEmbeddingService()
    l1_db = tmp_path / "l1_events.db"
    shared_db = tmp_path / "memory.db"

    l1_store = L1EventStore(db_path=str(l1_db), embedding_service=embedding_service, async_embeddings=False)
    l3_store = L3SummaryStore(db_path=str(shared_db), embedding_service=embedding_service, async_embeddings=False)
    l4_store = L4ProceduralMemoryStore(db_path=str(shared_db), embedding_service=embedding_service, async_embeddings=False)

    try:
        await l1_store.initialize()
        await l3_store.initialize()
        await l4_store.initialize()

        event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "message": "stress journal"},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-1",
            ),
            event_id="evt-1",
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
                    data={"action_type": "browser.open", "success": True, "execution_time": 0.2, "optimized_prompt": "browser stress playbook"},
                    source="runtime",
                    level=EventLevel.INFO,
                    correlation_id="corr-2",
                ),
                event_id="evt-2",
            )
        )

        assert _has_virtual_table_with_prefix(str(l1_db), "l1_event_vec_")
        assert _has_virtual_table_with_prefix(str(shared_db), "l3_summary_vec_")
        assert _has_virtual_table_with_prefix(str(shared_db), "l4_skill_vec_")
    finally:
        await l1_store.shutdown()
        await l3_store.shutdown()
        await l4_store.shutdown()
