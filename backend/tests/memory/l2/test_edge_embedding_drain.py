"""Verify pending edge embedding through the real pipeline and vector index."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import aiosqlite
import pytest

from magi.memory.embedding.embedding_service import EmbeddingResult, EmbeddingProfile
from magi.memory.embedding.sqlite_vec_index import SqliteVecIndex
from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer, L2EdgeEmbeddingWorker


class _EmbeddingProvider:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def embed_texts(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("fixture provider failed")
        return [
            EmbeddingResult(model_name="fixture-model", dimension=3, vector=[0.25, 0.5, 0.75])
            for _ in texts
        ]

    def get_active_profile(self, *, text_builder_version):
        return EmbeddingProfile.build(
            provider_name="fixture",
            model_name="fixture-model",
            dimension=3,
            text_builder_version=text_builder_version,
        )

    def profile_from_result(self, result, *, text_builder_version):
        return self.get_active_profile(text_builder_version=text_builder_version)

    def result_for_index(self, result, *, text_builder_version):
        return replace(
            result,
            index_identity=self.get_active_profile(
                text_builder_version=text_builder_version
            ).profile_id,
        )


def _index(db_path):
    return SqliteVecIndex(
        db_path=db_path,
        registry_table="l2_edge_vectors",
        entity_column="triple_id",
        vec_table_prefix="l2_edge_vec",
    )


async def _seed(store, object_id="person:jay"):
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u",
        subject_type="person",
        predicate="LIKES",
        object_id=object_id,
        object_type="person",
        evidence_event_ids=["e1"],
        confidence=1.0,
        observed_at=1.0,
        source_type="test",
        evidence_text="u likes jay",
    )

    async with aiosqlite.connect(store.db_path) as db:
        await db.execute("UPDATE knowledge_graph SET natural_summary=? WHERE triple_id=?", ("A music preference",triple_id))
        await db.commit()
    return triple_id


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_mode", [False, True])
async def test_drainer_persists_exact_vector_profile_and_finishes_worker(
    l2_store_with_schema, worker_mode
):
    store = l2_store_with_schema
    triple_id = await _seed(store)
    provider = _EmbeddingProvider()
    index = _index(store.db_path)
    drainer = EdgeEmbeddingDrainer(
        db_path=store.db_path, embedding_service=provider, edge_vector_index=index
    )
    worker = L2EdgeEmbeddingWorker(drainer=drainer, idle_interval_seconds=0.01)
    try:
        if worker_mode:
            await worker.start()
            task = worker._task
            assert task is not None
            async with asyncio.timeout(2):
                while await store.get_pending_edge_embeddings(limit=10):
                    await asyncio.sleep(0.01)
            await worker.stop()
            assert task.done() and worker._task is None
        else:
            assert await drainer.drain_once() == 1
        assert await store.get_pending_edge_embeddings(limit=10) == []
        assert provider.calls == [["user:u LIKES person:jay\nA music preference\nu likes jay"]]
        async with aiosqlite.connect(store.db_path) as db:
            state = await (
                await db.execute(
                    "SELECT embedding_status,embedding_profile_id,last_embedded_at FROM knowledge_graph WHERE triple_id=?",
                    (triple_id,),
                )
            ).fetchone()
            registry = await (
                await db.execute(
                    "SELECT triple_id,embedding_model,embedding_dim,metadata FROM l2_edge_vectors"
                )
            ).fetchall()
        from magi.memory.embedding.embedding_text_builders import (
            L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION,
        )

        profile = provider.get_active_profile(
            text_builder_version=L2_EDGE_EMBEDDING_TEXT_BUILDER_VERSION
        )
        assert state[0:2] == ("ready", profile.profile_id)
        assert state[2] > 0
        assert len(registry) == 1 and registry[0][:3] == (triple_id, profile.profile_id, 3)
        import json

        assert json.loads(registry[0][3]) == {"kind": "edge", "chunk_index": 0}
        await index.close()
        index = _index(store.db_path)
        assert await index.get_vectors(
            entity_ids=[triple_id], model_key=profile.profile_id, dimension=3
        ) == {triple_id: [0.25, 0.5, 0.75]}
        if worker_mode:
            next_id = await _seed(store, object_id="person:other")
            await asyncio.sleep(0)
            assert task.done()
            assert [
                row["triple_id"] for row in await store.get_pending_edge_embeddings(limit=10)
            ] == [next_id]
            assert len(provider.calls) == 1
    finally:
        await worker.stop()
        await index.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seed,has_service,has_index", [(False, True, True), (True, False, True), (True, True, False)]
)
async def test_empty_work_or_missing_dependency_does_not_call_provider(
    l2_store_with_schema, seed, has_service, has_index
):
    store = l2_store_with_schema
    triple_id = await _seed(store) if seed else None
    provider = _EmbeddingProvider()
    index = _index(store.db_path)
    try:
        drainer = EdgeEmbeddingDrainer(
            db_path=store.db_path,
            embedding_service=provider if has_service else None,
            edge_vector_index=index if has_index else None,
        )
        assert await drainer.drain_once() == 0
        assert provider.calls == []
        assert [row["triple_id"] for row in await store.get_pending_edge_embeddings(limit=10)] == (
            [triple_id] if seed else []
        )
        assert await index.get_vectors(entity_ids=[triple_id] if seed else ["missing"]) == {}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_failed_provider_keeps_pending_edge_and_writes_no_vector(
    l2_store_with_schema, caplog
):
    store = l2_store_with_schema
    triple_id = await _seed(store)
    provider = _EmbeddingProvider()
    provider.fail = True
    index = _index(store.db_path)
    try:
        drainer = EdgeEmbeddingDrainer(
            db_path=store.db_path, embedding_service=provider, edge_vector_index=index
        )
        assert await drainer.drain_once() == 0
        assert provider.calls == [["user:u LIKES person:jay\nA music preference\nu likes jay"]]
        assert "fixture provider failed" in caplog.text
        assert [row["triple_id"] for row in await store.get_pending_edge_embeddings(limit=10)] == [
            triple_id
        ]
        assert await index.get_vectors(entity_ids=[triple_id]) == {}
    finally:
        await index.close()
