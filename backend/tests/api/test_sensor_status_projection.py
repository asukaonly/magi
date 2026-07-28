from __future__ import annotations

from magi.api.routers.sensor_status_projection import _serialize_sensor_sync_activity


def test_serialize_sensor_sync_activity_exposes_backfill_range_and_result() -> None:
    activity = _serialize_sensor_sync_activity(
        {
            "job_id": "job-1",
            "status": "success",
            "payload": {
                "sync_request": {
                    "mode": "backfill",
                    "backfill_scope": "custom",
                    "backfill_start_date": "2026-06-01",
                    "backfill_end_date": "2026-06-30",
                }
            },
            "stats": {"items": 12},
            "created_at": 100.0,
            "started_at": 101.0,
            "finished_at": 102.0,
            "error": None,
        },
        now=110.0,
    )

    assert activity == {
        "job_id": "job-1",
        "mode": "backfill",
        "status": "success",
        "backfill_scope": "custom",
        "backfill_start_date": "2026-06-01",
        "backfill_end_date": "2026-06-30",
        "created_at": 100.0,
        "started_at": 101.0,
        "finished_at": 102.0,
        "attempt_count": 0,
        "next_attempt_at": None,
        "error": None,
    }


def test_serialize_sensor_sync_activity_keeps_batch_transition_active() -> None:
    activity = _serialize_sensor_sync_activity(
        {
            "job_id": "job-2",
            "status": "success",
            "payload": {
                "sync_request": {
                    "mode": "backfill",
                    "backfill_scope": "last_30_days",
                }
            },
            "stats": {"has_more": True},
            "created_at": 100.0,
            "started_at": 101.0,
            "finished_at": 109.0,
            "error": None,
        },
        now=110.0,
    )

    assert activity is not None
    assert activity["status"] == "continuing"
    assert activity["mode"] == "backfill"


def test_serialize_sensor_sync_activity_exposes_durable_retry_state() -> None:
    activity = _serialize_sensor_sync_activity(
        {
            "job_id": "job-3",
            "status": "queued",
            "payload": {},
            "stats": {},
            "attempt_count": 2,
            "next_attempt_at": 130.0,
            "created_at": 100.0,
            "started_at": None,
            "finished_at": None,
            "error": "temporary source failure",
        },
        now=110.0,
    )

    assert activity is not None
    assert activity["status"] == "retrying"
    assert activity["attempt_count"] == 2
    assert activity["next_attempt_at"] == 130.0
    assert activity["error"] == "temporary source failure"
