"""Tests for EdgeEmbeddingDrainer (#86)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.store import L2CognitionStore


def _migrate_memory_shared_schema(db_path: str) -> None:
    from alembic import command

    from magi.db.runner import MIGRATION_TARGETS, _build_config

    memory_shared_target = next(
        target for target in MIGRATION_TARGETS if target.name == "memory_shared"
    )
    command.upgrade(_build_config(memory_shared_target, Path(db_path)), "head")


async def _init_schema(db_path: str) -> None:
    _migrate_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    catalog = L2EntityCatalog(db_path=db_path)
    await catalog.initialize()


@pytest.mark.asyncio
async def test_drain_once_embeds_pending_edges() -> None:
    """drain_once() returns count of embedded edges and clears pending status."""
    from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "memory.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        tid = await store.upsert_knowledge_edge(
            subject_id="user:u",
            subject_type="person",
            predicate="LIKES",
            object_id="person:jay",
            object_type="person",
            evidence_event_ids=["e1"],
            confidence=1.0,
            observed_at=1.0,
            source_type="test",
            evidence_text="u likes jay",
        )

        # Build mock embedding service + vector index (same pattern as test_entity_maintenance.py)
        mock_embedding_service = MagicMock()
        mock_vector_index = MagicMock()

        mock_result = MagicMock()
        mock_result.parent_id = tid
        mock_result.embedded_at = time.time()
        mock_result.embeddings = [[0.1, 0.2, 0.3]]
        mock_embedding_service.profile_from_result.return_value = SimpleNamespace(
            profile_id="test-profile"
        )

        mock_pipeline_cls = AsyncMock()

        async def _prepare(items):
            mock_result.parent_id = items[0].parent_id
            mock_result.payload = items[0].payload
            return [mock_result]

        mock_pipeline_cls.prepare_items = AsyncMock(side_effect=_prepare)
        mock_pipeline_cls.persist_results = AsyncMock(side_effect=lambda results: results)

        drainer = EdgeEmbeddingDrainer(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        import magi.memory.l2.edge_embedding_drain as drain_module

        original_pipeline = drain_module.MemoryEmbeddingPipeline
        drain_module.MemoryEmbeddingPipeline = lambda **kwargs: mock_pipeline_cls

        try:
            count = await drainer.drain_once()
        finally:
            drain_module.MemoryEmbeddingPipeline = original_pipeline

        assert count == 1

        pending = await store.get_pending_edge_embeddings(limit=10)
        assert pending == []


@pytest.mark.asyncio
async def test_drain_once_empty_returns_zero() -> None:
    """drain_once() returns 0 when there are no pending edges."""
    from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "memory.db")
        await _init_schema(db_path)

        mock_embedding_service = MagicMock()
        mock_vector_index = MagicMock()

        drainer = EdgeEmbeddingDrainer(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        count = await drainer.drain_once()
        assert count == 0


@pytest.mark.asyncio
async def test_drain_once_swallows_pipeline_error() -> None:
    """drain_once() returns 0 and does not raise when the embedding pipeline throws."""
    from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "memory.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.upsert_knowledge_edge(
            subject_id="user:u",
            subject_type="person",
            predicate="LIKES",
            object_id="person:jay",
            object_type="person",
            evidence_event_ids=["e1"],
            confidence=1.0,
            observed_at=1.0,
            source_type="test",
            evidence_text="u likes jay",
        )

        mock_embedding_service = MagicMock()
        mock_vector_index = MagicMock()

        mock_pipeline_cls = AsyncMock()
        mock_pipeline_cls.prepare_items = AsyncMock(side_effect=RuntimeError("boom"))

        drainer = EdgeEmbeddingDrainer(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        import magi.memory.l2.edge_embedding_drain as drain_module

        original_pipeline = drain_module.MemoryEmbeddingPipeline
        drain_module.MemoryEmbeddingPipeline = lambda **kwargs: mock_pipeline_cls

        try:
            count = await drainer.drain_once()
        finally:
            drain_module.MemoryEmbeddingPipeline = original_pipeline

        assert count == 0

        # Edge must still be pending — nothing was marked ready
        pending = await store.get_pending_edge_embeddings(limit=10)
        assert len(pending) > 0


@pytest.mark.asyncio
async def test_drain_once_no_service_is_noop() -> None:
    """drain_once() returns 0 without error when service/index are None."""
    from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "memory.db")
        await _init_schema(db_path)

        drainer = EdgeEmbeddingDrainer(
            db_path=db_path,
            embedding_service=None,
            edge_vector_index=None,
        )

        count = await drainer.drain_once()
        assert count == 0


@pytest.mark.asyncio
async def test_worker_drains_then_stops_cleanly() -> None:
    """L2EdgeEmbeddingWorker drains pending edges and stops cleanly with no leaked task."""
    import asyncio
    import time

    from magi.memory.l2.edge_embedding_drain import EdgeEmbeddingDrainer, L2EdgeEmbeddingWorker

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "memory.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.upsert_knowledge_edge(
            subject_id="user:u",
            subject_type="person",
            predicate="LIKES",
            object_id="person:jay",
            object_type="person",
            evidence_event_ids=["e1"],
            confidence=1.0,
            observed_at=1.0,
            source_type="test",
            evidence_text="u likes jay",
        )

        mock_embedding_service = MagicMock()
        mock_vector_index = MagicMock()

        mock_result = MagicMock()
        mock_result.embedded_at = time.time()
        mock_result.embeddings = [[0.1, 0.2, 0.3]]
        mock_embedding_service.profile_from_result.return_value = SimpleNamespace(
            profile_id="test-profile"
        )

        mock_pipeline_cls = AsyncMock()

        async def _prepare(items):
            mock_result.parent_id = items[0].parent_id
            mock_result.payload = items[0].payload
            return [mock_result]

        mock_pipeline_cls.prepare_items = AsyncMock(side_effect=_prepare)
        mock_pipeline_cls.persist_results = AsyncMock(side_effect=lambda results: results)

        drainer = EdgeEmbeddingDrainer(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        import magi.memory.l2.edge_embedding_drain as drain_module

        original_pipeline = drain_module.MemoryEmbeddingPipeline

        def _patched_pipeline(**kwargs):
            # fix parent_id on mock_result to match the actual triple_id returned by upsert
            return mock_pipeline_cls

        drain_module.MemoryEmbeddingPipeline = _patched_pipeline

        try:
            worker = L2EdgeEmbeddingWorker(drainer=drainer, idle_interval_seconds=0.05)
            await worker.start()

            # Poll until pending edges are cleared (up to ~40 × 20ms = 800ms)
            for _ in range(40):
                await asyncio.sleep(0.02)
                pending = await store.get_pending_edge_embeddings(limit=1)
                if pending == []:
                    break

            await worker.stop()
        finally:
            drain_module.MemoryEmbeddingPipeline = original_pipeline

        pending = await store.get_pending_edge_embeddings(limit=1)
        assert pending == [], "Worker should have drained the pending edge"
        assert worker._task is None, "stop() must set _task to None (no leaked task)"
