"""Regression tests verifying vec_l2_edges vector cleanup on forgetting and relationship corrections."""

from __future__ import annotations

from dataclasses import replace

import aiosqlite
import pytest

from magi.memory.embedding.embedding_service import EmbeddingProfile, EmbeddingResult
from magi.memory.embedding.sqlite_vec_index import SqliteVecIndex
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer
from magi.memory.l2.entities.maintenance import L2EntityMaintenance


class _StubEmbeddingProvider:
    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(model_name="fixture-model", dimension=3, vector=[0.2, 0.4, 0.8])
            for _ in texts
        ]

    def get_active_profile(self, *, text_builder_version: str) -> EmbeddingProfile:
        return EmbeddingProfile.build(
            provider_name="fixture",
            model_name="fixture-model",
            dimension=3,
            text_builder_version=text_builder_version,
        )

    def profile_from_result(
        self,
        result: EmbeddingResult,
        *,
        text_builder_version: str,
    ) -> EmbeddingProfile:
        return self.get_active_profile(text_builder_version=text_builder_version)

    def result_for_index(
        self,
        result: EmbeddingResult,
        *,
        text_builder_version: str,
    ) -> EmbeddingResult:
        return replace(
            result,
            index_identity=self.get_active_profile(
                text_builder_version=text_builder_version
            ).profile_id,
        )


def _edge_index(db_path: str) -> SqliteVecIndex:
    return SqliteVecIndex(
        db_path=db_path,
        registry_table="l2_edge_vectors",
        entity_column="triple_id",
        vec_table_prefix="l2_edge_vec",
    )


async def _count_vector_rows(db_path: str, triple_id: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM l2_edge_vectors WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0] or 0) if row is not None else 0


async def _edge_embedding_state(db_path: str, triple_id: str) -> tuple[str, str]:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT status, embedding_status FROM knowledge_graph WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            return (str(row[0]), str(row[1]))


async def _seed_and_embed_edge(
    store,
    index: SqliteVecIndex,
    *,
    event_id: str,
    object_id: str,
    observed_at: float = 1000.0,
) -> str:
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="LIKES",
        object_id=object_id,
        object_type="topic",
        evidence_event_ids=[event_id],
        confidence=0.95,
        observed_at=observed_at,
        source_type="chat",
        evidence_text=f"user likes {object_id}",
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE knowledge_graph SET natural_summary = ? WHERE triple_id = ?",
            (f"Likes {object_id}", triple_id),
        )
        await db.commit()
    drainer = EdgeEmbeddingDrainer(
        db_path=store.db_path,
        embedding_service=_StubEmbeddingProvider(),
        edge_vector_index=index,
    )
    assert await drainer.drain_once() >= 1
    assert await _edge_embedding_state(store.db_path, triple_id) == ("active", "ready")
    assert await _count_vector_rows(store.db_path, triple_id) == 1
    return triple_id


@pytest.mark.asyncio
async def test_forget_source_event_disables_and_deletes_edge_vector_immediately(l2_store_with_schema):
    store = l2_store_with_schema
    index = _edge_index(store.db_path)
    store.set_edge_vector_index(index)
    try:
        triple_id = await _seed_and_embed_edge(
            store, index, event_id="evt-forget-1", object_id="topic:secret-hobby"
        )

        await store.forget_source_events(["evt-forget-1"], reason="user_forget")

        assert await _edge_embedding_state(store.db_path, triple_id) == ("archived", "disabled")
        assert await _count_vector_rows(store.db_path, triple_id) == 0
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_forget_time_range_disables_and_deletes_edge_vector_immediately(l2_store_with_schema):
    store = l2_store_with_schema
    index = _edge_index(store.db_path)
    store.set_edge_vector_index(index)
    try:
        triple_id = await _seed_and_embed_edge(
            store, index, event_id="evt-range-1", object_id="topic:vacation", observed_at=2000.0
        )

        await store.forget_time_range(start=1900.0, end=2100.0)

        assert await _edge_embedding_state(store.db_path, triple_id) == ("archived", "disabled")
        assert await _count_vector_rows(store.db_path, triple_id) == 0
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_relationship_correction_apply_and_revert_clean_edge_vectors(l2_store_with_schema):
    store = l2_store_with_schema
    index = _edge_index(store.db_path)
    store.set_edge_vector_index(index)
    try:
        original_id = await _seed_and_embed_edge(
            store, index, event_id="evt-corr-1", object_id="topic:coffee"
        )

        applied = await store.apply_relationship_correction(
            triple_id=original_id,
            request_id="req-corr-1",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": "topic:tea", "object_type": "topic"},
        )
        assert applied is not None
        replacement_id = applied["current_relationship"]["triple_id"]
        correction_id = applied["correction"]["correction_id"]

        assert await _edge_embedding_state(store.db_path, original_id) == ("user_rejected", "disabled")
        assert await _count_vector_rows(store.db_path, original_id) == 0

        # Embed the replacement edge, then revert the correction.
        drainer = EdgeEmbeddingDrainer(
            db_path=store.db_path,
            embedding_service=_StubEmbeddingProvider(),
            edge_vector_index=index,
        )
        assert await drainer.drain_once() >= 1
        assert await _count_vector_rows(store.db_path, replacement_id) == 1

        reverted = await store.revert_relationship_correction(
            correction_id=correction_id,
            request_id="req-revert-1",
            actor_id="user:self",
        )
        assert reverted is not None

        assert await _edge_embedding_state(store.db_path, replacement_id) == ("archived", "disabled")
        assert await _count_vector_rows(store.db_path, replacement_id) == 0
        # Restored original edge is marked pending so the drainer re-embeds it cleanly.
        assert await _edge_embedding_state(store.db_path, original_id) == ("active", "pending")
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_maintenance_cleans_legacy_archived_pending_orphan_edge_vectors(l2_store_with_schema):
    store = l2_store_with_schema
    index = _edge_index(store.db_path)
    try:
        triple_id = await _seed_and_embed_edge(
            store, index, event_id="evt-legacy-1", object_id="topic:legacy-orphan"
        )
        # Simulate pre-fix bug state: archived edge left in 'pending' with stale vector row still in vec index.
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                "UPDATE knowledge_graph SET status = 'archived', embedding_status = 'pending' WHERE triple_id = ?",
                (triple_id,),
            )
            await db.commit()
        assert await _count_vector_rows(store.db_path, triple_id) == 1

        maintenance = L2EntityMaintenance(
            db_path=store.db_path,
            embedding_service=_StubEmbeddingProvider(),
            edge_vector_index=index,
        )
        stats = await maintenance.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
        )

        assert stats.errors == []
        assert stats.edge_embeddings_cleaned == 1
        assert await _edge_embedding_state(store.db_path, triple_id) == ("archived", "disabled")
        assert await _count_vector_rows(store.db_path, triple_id) == 0
    finally:
        await index.close()
