from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from magi.memory.embedding import vector_admin
from magi.memory.embedding.vector_admin import (
    EmbeddingRebuildManager,
    build_embedding_config_preflight,
)
from magi.utils.runtime import RuntimePaths


async def _ready_counts(**counts: int) -> dict[str, int]:
    return {"l1": 0, "l2_entities": 0, "l2_edges": 0, "l3": 0, "l4": 0, **counts}


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
    started_job = await manager.start_rebuild(unified_memory=object(), layers=["l1"])
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
