"""Wiring-assertion tests: L2EdgeEmbeddingWorker is wired into UnifiedMemoryStore (#86).

We assert that after initialize() the worker exists and its background task is
running (when embedding_service is provided), and after shutdown() it is stopped
(_task is None). Full end-to-end drain behaviour is covered by
tests/memory/l2/test_edge_embedding_drain.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_embedding_service() -> MagicMock:
    """Return a minimal mock embedding service."""
    svc = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_edge_embedding_worker_started_on_initialize(tmp_path: Path) -> None:
    """After initialize(), _edge_embedding_worker exists and its task is live."""
    from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore

    store = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"),
        l1_db_path=str(tmp_path / "l1.db"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        embedding_service=_make_embedding_service(),
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=True,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )

    await store.initialize()
    try:
        assert hasattr(store, "_edge_embedding_worker"), (
            "UnifiedMemoryStore must expose _edge_embedding_worker after initialize()"
        )
        worker = store._edge_embedding_worker
        assert worker is not None
        assert worker._task is not None, "worker task must be running after initialize()"
        assert not worker._task.done(), "worker task must not have already finished"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_edge_embedding_worker_stopped_on_shutdown(tmp_path: Path) -> None:
    """After shutdown(), _edge_embedding_worker._task is None (no leaked task)."""
    from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore

    store = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"),
        l1_db_path=str(tmp_path / "l1.db"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        embedding_service=_make_embedding_service(),
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=True,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )

    await store.initialize()
    await store.shutdown()

    worker = store._edge_embedding_worker
    assert worker is not None
    assert worker._task is None, "stop() must clear _task (no leaked background task)"


@pytest.mark.asyncio
async def test_edge_embedding_worker_not_started_without_embedding_service(tmp_path: Path) -> None:
    """When embedding_service is None, _edge_embedding_worker is created but never started."""
    from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore

    store = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"),
        l1_db_path=str(tmp_path / "l1.db"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        embedding_service=None,  # vectors disabled
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )

    await store.initialize()
    try:
        # Worker attribute exists but task must not be running
        assert hasattr(store, "_edge_embedding_worker")
        worker = store._edge_embedding_worker
        assert worker is not None
        assert worker._task is None, (
            "worker must not be started when embedding_service is None"
        )
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_edge_embedding_worker_uses_config_interval(tmp_path: Path) -> None:
    """_edge_embedding_worker idle interval matches memory_config_getter().l2.edge_embedding_drain_interval_seconds."""
    from types import SimpleNamespace

    from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore

    config_l2 = SimpleNamespace(
        enabled=True,
        vectors_enabled=True,
        batch_flush_interval_seconds=60,
        auto_extract_relations=False,
        maintenance_enabled=False,
        maintenance_interval_seconds=86400.0,
        edge_embedding_drain_interval_seconds=42.0,
        maintenance_min_mentions=2,
    )
    config = SimpleNamespace(
        l2=config_l2,
    )

    store = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"),
        l1_db_path=str(tmp_path / "l1.db"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        embedding_service=_make_embedding_service(),
        memory_config_getter=lambda: config,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=True,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )

    await store.initialize()
    try:
        worker = store._edge_embedding_worker
        assert worker._idle_interval == 42.0, (
            f"expected idle_interval=42.0 from config, got {worker._idle_interval}"
        )
    finally:
        await store.shutdown()
