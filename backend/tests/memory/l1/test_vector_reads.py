"""Identity-safe raw-vector reads for L1 semantic relationships."""

from __future__ import annotations

import pytest

from magi.memory.embedding.embedding_service import EmbeddingProfile, EmbeddingResult
from magi.memory.l1.embeddings.common import EMBEDDING_TEXT_BUILDER_VERSION
from magi.memory.l1.event_store import L1EventStore


class _ActiveProfileService:
    def get_active_profile(self, *, text_builder_version: str) -> EmbeddingProfile:
        return EmbeddingProfile.build(
            provider_name="test",
            model_name="current-model",
            dimension=3,
            text_builder_version=text_builder_version,
        )


@pytest.mark.asyncio
async def test_event_vector_reads_only_use_the_active_profile(tmp_path):
    service = _ActiveProfileService()
    store = L1EventStore(
        db_path=str(tmp_path / "l1.db"),
        embedding_service=service,  # type: ignore[arg-type]
        async_embeddings=False,
    )
    await store.initialize()
    assert store._vector_index is not None
    active_profile = service.get_active_profile(text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION)
    try:
        await store._vector_index.upsert(
            entity_id="event-1::chunk-0",
            embedding=EmbeddingResult(
                model_name="old-model",
                dimension=2,
                vector=[0.0, 1.0],
                index_identity="old-profile",
            ),
        )
        await store._vector_index.upsert(
            entity_id="event-2::chunk-0",
            embedding=EmbeddingResult(
                model_name="old-model",
                dimension=2,
                vector=[1.0, 0.0],
                index_identity="old-profile",
            ),
        )
        await store._vector_index.upsert(
            entity_id="event-1::chunk-0",
            embedding=EmbeddingResult(
                model_name="current-model",
                dimension=3,
                vector=[0.0, 0.0, 1.0],
                index_identity=active_profile.profile_id,
            ),
        )

        assert await store.get_event_vectors(["event-1", "event-2"]) == {
            "event-1": pytest.approx([0.0, 0.0, 1.0])
        }
    finally:
        await store.shutdown()
