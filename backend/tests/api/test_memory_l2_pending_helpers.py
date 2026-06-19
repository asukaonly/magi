from __future__ import annotations

from magi.api.routers.memory.helpers import build_l2_pending_breakdown


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
