from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from magi.memory.embedding import vector_admin
from magi.memory.embedding.vector_admin import (
    EmbeddingRebuildPausedError,
    EmbeddingRebuildManager,
    build_embedding_config_preflight,
)
from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.operation_barrier import AsyncOperationBarrier
from magi.utils.runtime import RuntimePaths


async def _ready_counts(**counts: int) -> dict[str, int]:
    return {"l1": 0, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0, **counts}


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.cleared = False
        self.items: list[dict] = []

    async def clear(self) -> None:
        self.cleared = True

    async def upsert_many(self, items: list[dict]) -> None:
        self.items.extend(items)


class _RecordingEmbeddingService:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_texts(self, texts: list[str]):
        self.texts.extend(texts)
        return [
            EmbeddingResult(
                model_name="test-embedding",
                dimension=3,
                vector=[0.1, 0.2, 0.3],
            )
            for _ in texts
        ]

    def profile_from_result(self, result, *, text_builder_version: str):  # type: ignore[no-untyped-def]
        return SimpleNamespace(profile_id=f"profile:{text_builder_version}")


def _memory_layer(enabled: bool = True, vectors_enabled: bool = True):
    return SimpleNamespace(enabled=enabled, vectors_enabled=vectors_enabled)


def _config(*, provider_id: str, model: str, dimension: int, base_url: str):
    provider = SimpleNamespace(
        provider_type="openai",
        api_format="openai",
        base_url=base_url,
        services=SimpleNamespace(embedding=SimpleNamespace(base_url=base_url)),
    )
    return SimpleNamespace(
        memory=SimpleNamespace(
            embedding=SimpleNamespace(mode="remote"),
            l1=_memory_layer(),
            l2=_memory_layer(),
            l3=_memory_layer(),
            l4=_memory_layer(),
        ),
        llm=SimpleNamespace(
            selections={
                "embedding": SimpleNamespace(
                    provider_id=provider_id,
                    model=model,
                    embedding_dimension=dimension,
                )
            },
            providers={provider_id: provider},
        ),
    )


def _create_l2_edge_embedding_db(db_path) -> None:
    with sqlite3.connect(db_path) as db:
        db.executescript("""
            CREATE TABLE entity_catalog (
                entity_id TEXT PRIMARY KEY,
                canonical_name TEXT
            );
            CREATE TABLE knowledge_graph (
                triple_id TEXT PRIMARY KEY,
                subject_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_id TEXT NOT NULL,
                evidence_text TEXT,
                natural_summary TEXT,
                status TEXT NOT NULL,
                updated_at REAL NOT NULL,
                embedding_status TEXT,
                embedding_profile_id TEXT,
                last_embedded_at REAL
            );
            """)
        db.executemany(
            "INSERT INTO entity_catalog(entity_id, canonical_name) VALUES (?, ?)",
            [("user:u1", "User"), ("topic:tea", "Tea"), ("topic:coffee", "Coffee")],
        )
        db.executemany(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, predicate, object_id, evidence_text,
                natural_summary, status, updated_at, embedding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _l2_edge_rows(),
        )
        db.commit()


def _l2_edge_rows() -> list[tuple]:
    return [
        (
            "edge-new",
            "user:u1",
            "LIKES",
            "topic:tea",
            "likes tea",
            "",
            "active",
            2,
            "stale",
        ),
        (
            "edge-old",
            "user:u1",
            "DISLIKES",
            "topic:coffee",
            "",
            "dislikes coffee",
            "active",
            1,
            "stale",
        ),
        (
            "edge-inactive",
            "user:u1",
            "LIKES",
            "topic:coffee",
            "inactive",
            "",
            "deprecated",
            3,
            "ready",
        ),
    ]


def _edge_embedding_rows_by_id(db_path) -> dict[str, tuple]:
    with sqlite3.connect(db_path) as db:
        return {row[0]: row[1:] for row in db.execute("""
                SELECT triple_id, embedding_status, embedding_profile_id, last_embedded_at
                FROM knowledge_graph
                ORDER BY triple_id
                """)}


@pytest.mark.asyncio
async def test_rebuild_l2_edge_embeddings_marks_active_edges_ready(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    _create_l2_edge_embedding_db(db_path)
    progress: list[int] = []
    index = _RecordingVectorIndex()
    service = _RecordingEmbeddingService()

    count = await vector_admin.rebuild_l2_edge_embeddings(
        db_path=str(db_path),
        embedding_service=service,
        vector_index=index,
        batch_size=1,
        progress_callback=lambda processed: _append_progress(progress, processed),
    )

    assert count == 2
    assert progress == [1, 2]
    assert index.cleared is True
    assert len(index.items) == 2
    assert len(service.texts) == 2

    rows = _edge_embedding_rows_by_id(db_path)
    assert rows["edge-new"][0] == "ready"
    assert rows["edge-old"][0] == "ready"
    assert rows["edge-new"][1].startswith("profile:")
    assert rows["edge-old"][1].startswith("profile:")
    assert rows["edge-new"][2] is not None
    assert rows["edge-inactive"][0] == "ready"


async def _append_progress(progress: list[int], processed: int) -> None:
    progress.append(processed)


@pytest.mark.asyncio
async def test_embedding_preflight_warns_strong_for_model_identity_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.memory.embedding.vector_admin.collect_vector_ready_counts",
        lambda: _ready_counts(l1=2),
    )

    result = await build_embedding_config_preflight(
        current_config=_config(
            provider_id="openai",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
        ),
        proposed_config=_config(
            provider_id="openai",
            model="text-embedding-3-large",
            dimension=3072,
            base_url="https://api.openai.com/v1",
        ),
    )

    assert result["severity"] == "strong"
    assert result["requires_rebuild"] is True
    assert result["warnings"][0]["reason"] == "hard_identity_changed"
    assert result["warnings"][0]["layer"] == "l1"


@pytest.mark.asyncio
async def test_embedding_preflight_warns_soft_for_remote_provider_provenance_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.memory.embedding.vector_admin.collect_vector_ready_counts",
        lambda: _ready_counts(l1=1),
    )

    result = await build_embedding_config_preflight(
        current_config=_config(
            provider_id="openai",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
        ),
        proposed_config=_config(
            provider_id="openrouter",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://openrouter.ai/api/v1",
        ),
    )

    assert result["severity"] == "soft"
    assert result["requires_rebuild"] is False
    assert result["warnings"][0]["reason"] == "remote_provider_changed"


@pytest.mark.asyncio
async def test_embedding_preflight_ignores_layers_without_ready_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.memory.embedding.vector_admin.collect_vector_ready_counts",
        lambda: _ready_counts(),
    )

    result = await build_embedding_config_preflight(
        current_config=_config(
            provider_id="openai",
            model="text-embedding-3-small",
            dimension=1536,
            base_url="https://api.openai.com/v1",
        ),
        proposed_config=_config(
            provider_id="openai",
            model="text-embedding-3-large",
            dimension=3072,
            base_url="https://api.openai.com/v1",
        ),
    )

    assert result["severity"] == "none"
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_embedding_rebuild_job_persists_running_batch_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    progress_seen = asyncio.Event()
    release_rebuild = asyncio.Event()

    async def fake_source_counts() -> dict[str, int]:
        return {"l1": 5, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0}

    async def fake_run_rebuild_layer(unified_memory, layer, *, progress_callback=None) -> int:
        assert layer == "l1"
        assert unified_memory is not None
        assert progress_callback is not None
        await progress_callback(3)
        progress_seen.set()
        await release_rebuild.wait()
        return 5

    monkeypatch.setattr(vector_admin, "get_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(vector_admin, "collect_vector_rebuild_source_counts", fake_source_counts)
    monkeypatch.setattr(vector_admin, "_run_rebuild_layer", fake_run_rebuild_layer)

    manager = EmbeddingRebuildManager()
    barrier = AsyncOperationBarrier()
    unified_memory = SimpleNamespace(memory_operation_guard=barrier.operation)
    started_job = await manager.start_rebuild(unified_memory=unified_memory, layers=["l1"])
    await asyncio.wait_for(progress_seen.wait(), timeout=1)

    running_job = await manager.get_job(started_job["job_id"])
    assert running_job is not None
    assert running_job["status"] == "running"
    assert running_job["total_items"] == 5
    assert running_job["processed_items"] == 3
    assert running_job["layers"][0]["processed_items"] == 3

    release_rebuild.set()
    for _ in range(20):
        finished_job = await manager.get_job(started_job["job_id"])
        if finished_job is not None and finished_job["terminal"]:
            break
        await asyncio.sleep(0.01)

    assert finished_job is not None
    assert finished_job["status"] == "succeeded"
    assert finished_job["processed_items"] == 5


@pytest.mark.asyncio
async def test_embedding_rebuild_job_normalizes_legacy_low_totals(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    monkeypatch.setattr(vector_admin, "get_runtime_paths", lambda: runtime_paths)

    manager = EmbeddingRebuildManager()
    await manager._ensure_schema()
    job_id = "legacy-low-total"
    with sqlite3.connect(runtime_paths.memory_db_path) as db:
        db.execute(
            """
            INSERT INTO embedding_rebuild_jobs(
                job_id, status, requested_layers_json, active_layer,
                total_items, processed_items, succeeded_items, failed_items,
                cancel_requested, error, created_at, started_at, finished_at, updated_at
            ) VALUES (?, 'succeeded', ?, NULL, 1, 3, 3, 0, 0, NULL, 1, 1, 2, 2)
            """,
            (job_id, '["l2_edges"]'),
        )
        db.execute(
            """
            INSERT INTO embedding_rebuild_job_layers(
                job_id, layer, status, total_items, processed_items,
                succeeded_items, failed_items, error, started_at, finished_at, updated_at
            ) VALUES (?, 'l2_edges', 'succeeded', 0, 3, 3, 0, NULL, 1, 2, 2)
            """,
            (job_id,),
        )
        db.commit()

    job = await manager.get_job(job_id)

    assert job is not None
    assert job["total_items"] == 3
    assert job["processed_items"] == 3
    assert job["layers"][0]["total_items"] == 3
    assert job["layers"][0]["processed_items"] == 3


@pytest.mark.asyncio
async def test_pause_cancels_active_rebuild_before_exclusive_clear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    rebuild_entered = asyncio.Event()

    async def fake_source_counts() -> dict[str, int]:
        return {"l1": 1, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0}

    async def blocked_rebuild(_memory, _layer, *, progress_callback=None) -> int:
        rebuild_entered.set()
        await asyncio.Event().wait()
        return 1

    monkeypatch.setattr(vector_admin, "get_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(vector_admin, "collect_vector_rebuild_source_counts", fake_source_counts)
    monkeypatch.setattr(vector_admin, "_run_rebuild_layer", blocked_rebuild)

    manager = EmbeddingRebuildManager()
    barrier = AsyncOperationBarrier()
    memory = SimpleNamespace(memory_operation_guard=barrier.operation)
    job = await manager.start_rebuild(unified_memory=memory, layers=["l1"])
    await asyncio.wait_for(rebuild_entered.wait(), timeout=1)

    cancelled_count = await asyncio.wait_for(
        manager.pause_starts_and_cancel_all(),
        timeout=1,
    )
    async with barrier.exclusive():
        pass

    cancelled_job = await manager.get_job(job["job_id"])
    assert cancelled_count == 1
    assert cancelled_job is not None
    assert cancelled_job["status"] == "cancelled"
    assert manager._tasks == {}


@pytest.mark.asyncio
async def test_pause_wins_against_start_waiting_for_manager_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    monkeypatch.setattr(vector_admin, "get_runtime_paths", lambda: runtime_paths)

    manager = EmbeddingRebuildManager()
    await manager._lock.acquire()
    pause_task = asyncio.create_task(manager.pause_starts_and_cancel_all())
    await asyncio.sleep(0)
    start_task = asyncio.create_task(
        manager.start_rebuild(
            unified_memory=SimpleNamespace(
                memory_operation_guard=AsyncOperationBarrier().operation
            ),
            layers=["l1"],
        )
    )
    await asyncio.sleep(0)
    manager._lock.release()

    assert await asyncio.wait_for(pause_task, timeout=1) == 0
    with pytest.raises(EmbeddingRebuildPausedError):
        await asyncio.wait_for(start_task, timeout=1)
    assert manager._tasks == {}


@pytest.mark.asyncio
async def test_pause_cancels_job_created_immediately_before_pause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")
    run_started = asyncio.Event()

    async def fake_source_counts() -> dict[str, int]:
        return {"l1": 0, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0}

    async def blocked_run(_job_id, _memory, _layers) -> None:
        run_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(vector_admin, "get_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(vector_admin, "collect_vector_rebuild_source_counts", fake_source_counts)
    manager = EmbeddingRebuildManager()
    monkeypatch.setattr(manager, "_run_job", blocked_run)
    memory = SimpleNamespace(memory_operation_guard=AsyncOperationBarrier().operation)

    start_task = asyncio.create_task(manager.start_rebuild(unified_memory=memory, layers=["l1"]))
    await asyncio.wait_for(run_started.wait(), timeout=1)
    pause_task = asyncio.create_task(manager.pause_starts_and_cancel_all())
    job = await asyncio.wait_for(start_task, timeout=1)

    assert await asyncio.wait_for(pause_task, timeout=1) == 1
    cancelled_job = await manager.get_job(job["job_id"])
    assert cancelled_job is not None
    assert cancelled_job["status"] == "cancelled"
    assert manager._tasks == {}


@pytest.mark.asyncio
async def test_failed_pause_can_be_resumed_and_accepts_a_new_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    runtime_paths = RuntimePaths(tmp_path / "runtime")

    async def fake_source_counts() -> dict[str, int]:
        return {"l1": 0, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0}

    monkeypatch.setattr(vector_admin, "get_runtime_paths", lambda: runtime_paths)
    monkeypatch.setattr(
        vector_admin,
        "collect_vector_rebuild_source_counts",
        fake_source_counts,
    )
    manager = EmbeddingRebuildManager()
    original_await_cancelled = manager._await_cancelled_tasks
    pause_attempts = 0

    async def fail_first_pause(active) -> None:  # type: ignore[no-untyped-def]
        nonlocal pause_attempts
        pause_attempts += 1
        if pause_attempts == 1:
            raise RuntimeError("pause cleanup failed")
        await original_await_cancelled(active)

    monkeypatch.setattr(manager, "_await_cancelled_tasks", fail_first_pause)

    with pytest.raises(RuntimeError, match="pause cleanup failed"):
        await manager.pause_starts_and_cancel_all()

    await manager.resume_starts()
    job = await manager.start_rebuild(
        unified_memory=SimpleNamespace(
            memory_operation_guard=AsyncOperationBarrier().operation,
        ),
        layers=["l1"],
    )
    for _ in range(50):
        current = await manager.get_job(job["job_id"])
        if current is not None and current["terminal"]:
            break
        await asyncio.sleep(0.01)

    assert current is not None
    assert current["status"] == "succeeded"
