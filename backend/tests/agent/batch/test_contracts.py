from magi.agent.batch.contracts import (
    BatchItemStatus,
    BatchJob,
    BatchJobStatus,
    ItemOutcome,
    ReconcileReport,
    TERMINAL_ITEM_STATUSES,
)


def test_item_status_terminal_set():
    assert BatchItemStatus.DONE in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.FAILED in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.SKIPPED in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.PENDING not in TERMINAL_ITEM_STATUSES
    assert BatchItemStatus.NEEDS_REVIEW not in TERMINAL_ITEM_STATUSES


def test_status_enums_are_str_valued():
    assert BatchJobStatus.RUNNING.value == "running"
    assert BatchItemStatus.NEEDS_REVIEW.value == "needs_review"


def test_job_and_item_are_value_equal():
    a = BatchJob(
        job_id="j1", title="t", owner="local_user", origin_session_id="s1",
        origin_turn_id="u1", handler_ref="movie-rename", handler_config={},
        seed_spec={}, status=BatchJobStatus.PLANNING, batch_size=15,
        concurrency=1, max_attempts=3,
        created_at_ms=1, updated_at_ms=1,
    )
    b = BatchJob(
        job_id="j1", title="t", owner="local_user", origin_session_id="s1",
        origin_turn_id="u1", handler_ref="movie-rename", handler_config={},
        seed_spec={}, status=BatchJobStatus.PLANNING, batch_size=15,
        concurrency=1, max_attempts=3,
        created_at_ms=1, updated_at_ms=1,
    )
    assert a == b


def test_item_outcome_defaults():
    oc = ItemOutcome(item_id="i1", status=BatchItemStatus.DONE)
    assert oc.result is None
    assert oc.review_reason is None
    assert oc.error is None


def test_reconcile_report_shape():
    rep = ReconcileReport(
        job_id="j1", counts={"done": 2}, total=2, conflicts=[],
        reclaimed_leases=0, complete=True,
    )
    assert rep.complete is True
    assert rep.counts["done"] == 2
