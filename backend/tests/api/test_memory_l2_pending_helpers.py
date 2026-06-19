from __future__ import annotations

from magi.api.routers.memory.helpers import build_embedding_pending, build_l2_pending_breakdown


def test_l2_pending_breakdown_counts_in_memory_extract_work() -> None:
    pending = build_l2_pending_breakdown(
        {
            "extract_enqueued": 10,
            "extract_completed": 2,
            "extract_failed": 0,
            "extract_skipped": 0,
            "reconcile_enqueued": 0,
            "reconcile_completed": 0,
            "reconcile_failed": 0,
            "snapshot_enqueued": 0,
            "snapshot_completed": 0,
            "snapshot_failed": 0,
        },
        {
            "pending": 1,
            "claimed": 2,
            "failed": 0,
        },
    )

    assert pending["extract_pending"] == 8
    assert pending["projection_pending"] == 1
    assert pending["projection_claimed"] == 2


def test_l2_pending_breakdown_counts_active_l2_workers() -> None:
    pending = build_l2_pending_breakdown(
        {
            "extract_enqueued": 0,
            "extract_completed": 0,
            "extract_failed": 0,
            "extract_skipped": 0,
            "extract_active": 2,
            "reconcile_enqueued": 0,
            "reconcile_completed": 0,
            "reconcile_failed": 0,
            "reconcile_active": 1,
            "snapshot_enqueued": 0,
            "snapshot_completed": 0,
            "snapshot_failed": 0,
            "snapshot_active": 1,
        },
        {
            "pending": 0,
            "claimed": 0,
            "failed": 0,
        },
    )

    assert pending["extract_pending"] == 2
    assert pending["reconcile_pending"] == 1
    assert pending["snapshot_pending"] == 1
    assert pending["extract_active"] == 2
    assert pending["reconcile_active"] == 1
    assert pending["snapshot_active"] == 1


def test_embedding_pending_counts_active_embedding_work() -> None:
    pending = build_embedding_pending(
        {
            "embedding_queue_size": 0,
            "embedding_active_count": 1,
            "embedding_worker_running": True,
            "vector_enabled": True,
            "async_embeddings": True,
        }
    )

    assert pending["pending"] == 1
    assert pending["queued"] == 0
    assert pending["active"] == 1
    assert pending["worker_running"] is True
