from __future__ import annotations

from magi.memory.l2.models import L2PendingBatchBucket


def test_microbatch_job_preserves_sequence_within_one_session() -> None:
    bucket = L2PendingBatchBucket.for_owner(session_id="s1", user_id="u1")
    bucket.add_event(
        {
            "event_id": "evt-0",
            "timestamp": 20.0,
            "session_id": "s1",
            "session_seq": 0,
            "user_id": "u1",
            "content": "first by source order",
        },
        estimated_tokens=8,
    )
    bucket.add_event(
        {
            "event_id": "evt-1",
            "timestamp": 10.0,
            "session_id": "s1",
            "session_seq": 1,
            "user_id": "u1",
            "content": "second despite an older timestamp",
        },
        estimated_tokens=8,
    )

    job = bucket.build_job(flush_reason="interval_elapsed")

    assert job.event_ids == ["evt-0", "evt-1"]
    assert [item["session_seq"] for item in job.events] == [0, 1]
    assert job.oldest_event_timestamp == 10.0
    assert job.newest_event_timestamp == 20.0


def test_microbatch_job_keeps_cross_session_timestamp_positions() -> None:
    bucket = L2PendingBatchBucket.for_owner(user_id="u1")
    for event in (
        {
            "event_id": "s1-first",
            "timestamp": 40.0,
            "session_id": "s1",
            "session_seq": 0,
        },
        {
            "event_id": "s2-only",
            "timestamp": 20.0,
            "session_id": "s2",
            "session_seq": 0,
        },
        {
            "event_id": "s1-second",
            "timestamp": 10.0,
            "session_id": "s1",
            "session_seq": 1,
        },
    ):
        bucket.add_event(event, estimated_tokens=1)

    job = bucket.build_job(flush_reason="interval_elapsed")

    assert job.event_ids == ["s1-first", "s2-only", "s1-second"]
