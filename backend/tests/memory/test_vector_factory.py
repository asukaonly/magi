"""Use real vector storage independently of structured memory databases."""

from pathlib import Path

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.embedding.sqlite_factory import SqliteVectorIndexFactory
from magi.memory.l1.event_store import L1EventStore
from magi.memory.unified_store import UnifiedMemoryStore
from memory.test_clear_embedding_barrier import _DeterministicEmbeddingService, _user_message


@pytest.mark.asyncio
async def test_l1_ingests_searches_and_rebuilds_with_separate_vector_storage(tmp_path):
    source = str(tmp_path / "source.db")
    vectors = str(tmp_path / "vectors.db")
    factory = SqliteVectorIndexFactory(l1_db_path=vectors, memory_db_path=vectors)
    store = L1EventStore(
        db_path=source,
        vector_index_factory=factory,
        embedding_service=_DeterministicEmbeddingService(),
        async_embeddings=False,
    )
    await store.initialize()
    try:
        await store.store(_user_message(event_id="travel", content="Travel preference."))
        hits = await store.vector_search(query="Travel")
        assert hits
        assert [item["event_id"] for item in await store.search_events(query="Travel")] == [
            "travel"
        ]
        assert await store.rebuild_embeddings(batch_size=1) == 1
        async with sqlite_connection_async(source) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'l1_event_vec%'"
            ) as cursor:
                assert await cursor.fetchall() == []
        # A stale derived hit alone must not resurrect a cleared source event.
        await store.clear(restart_workers=False)
        await factory.create("l1").upsert(
            entity_id=hits[0].entity_id,
            embedding=_DeterministicEmbeddingService._result("Travel"),
        )
        assert await store.vector_search(query="Travel")
        assert await store.search_events(query="Travel") == []
        assert await store.rebuild_embeddings(batch_size=1) == 0
        assert await store.vector_search(query="Travel") == []
    finally:
        await store.shutdown()
        await factory.close()


@pytest.mark.asyncio
async def test_full_clear_removes_external_indexes_with_every_layer_disabled(
    tmp_path, ensure_db_schema
):
    vectors = str(tmp_path / "vectors.db")
    layers = ("l1", "l2_entities", "l2_edges", "l3", "l4")
    factory = SqliteVectorIndexFactory(l1_db_path=vectors, memory_db_path=vectors)
    for layer in layers:
        await factory.create(layer).upsert(
            entity_id="retained",
            embedding=_DeterministicEmbeddingService._result("Travel"),
            metadata={"private": "private-vector-marker-879a143e"},
        )
    await factory.close()
    factory = SqliteVectorIndexFactory(l1_db_path=vectors, memory_db_path=vectors)
    shared = str(tmp_path / "memory.db")
    ensure_db_schema("memory_shared", shared)
    memory = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "source.db"),
        memory_db_path=shared,
        persist_dir=str(tmp_path),
        vector_index_factory=factory,
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await memory.initialize(start_workers=False)
    try:
        await memory.clear_all_memory()
        for suffix in ("", "-wal", "-shm"):
            path = Path(vectors + suffix)
            if path.exists():
                assert b"private-vector-marker-879a143e" not in path.read_bytes()
        for layer in layers:
            assert await factory.create(layer).get_vectors(entity_ids=["retained"]) == {}
    finally:
        await memory.shutdown()
