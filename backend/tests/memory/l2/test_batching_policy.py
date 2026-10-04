"""Unit tests for durable L2 projection batching policy."""

from __future__ import annotations

import pytest

from magi.memory.l2.batching_policy import (
    BatchingPolicy,
    BucketState,
    FlushReason,
    decide_flush,
)


def _state(*, event_count: int = 1, estimated_tokens: int = 100, oldest_age_seconds: float = 0.0) -> BucketState:
    return BucketState(
        event_count=event_count,
        estimated_tokens=estimated_tokens,
        oldest_age_seconds=oldest_age_seconds,
    )


def test_empty_bucket_never_flushes():
    state = _state(event_count=0, estimated_tokens=0, oldest_age_seconds=999.0)
    assert decide_flush(state, BatchingPolicy(), batching_enabled=True) is None
    assert decide_flush(state, BatchingPolicy(), batching_enabled=False) is None


@pytest.mark.parametrize(
    "case_token_limit,case_wait_limit,case_estimated_tokens",
    [
        pytest.param(10000, 999.0, 50, id="max_events_takes_precedence_over_other_conditions"),
        pytest.param(100, 60.0, 200, id="max_events_priority_over_token_cap"),
    ],
)
def test_event_count_trigger_precedes_other_batch_thresholds(
    case_token_limit, case_wait_limit, case_estimated_tokens
):
    policy = BatchingPolicy(
        max_events=3, max_estimated_tokens=case_token_limit, max_wait_seconds=case_wait_limit
    )
    state = _state(event_count=3, estimated_tokens=case_estimated_tokens, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=True) is FlushReason.MAX_EVENTS


def test_token_cap_triggers_when_below_max_events():
    policy = BatchingPolicy(max_events=12, max_estimated_tokens=2400, max_wait_seconds=60.0)
    state = _state(event_count=2, estimated_tokens=2400, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=True) is FlushReason.TOKEN_CAP


def test_interval_elapsed_triggers_after_max_wait():
    policy = BatchingPolicy(max_events=12, max_estimated_tokens=2400, max_wait_seconds=60.0)
    state = _state(event_count=1, estimated_tokens=10, oldest_age_seconds=60.0)
    assert decide_flush(state, policy, batching_enabled=True) is FlushReason.INTERVAL_ELAPSED


@pytest.mark.parametrize("age", [5.0, -5.0])
def test_under_budget_batches_wait_despite_clock_skew(age):
    policy = BatchingPolicy(max_events=12, max_estimated_tokens=2400, max_wait_seconds=60.0)
    state = _state(event_count=1, estimated_tokens=10, oldest_age_seconds=age)
    assert decide_flush(state, policy, batching_enabled=True) is None


def test_batching_disabled_flushes_any_non_empty_bucket_immediately():
    """When the host disables batching, any pending events should drain right away.

    This preserves the 'interval=0 means no batching' contract used by tests
    that want synchronous L2 extraction.
    """
    policy = BatchingPolicy(max_events=12, max_estimated_tokens=2400, max_wait_seconds=60.0)
    state = _state(event_count=1, estimated_tokens=10, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=False) is FlushReason.INTERVAL_ELAPSED


def test_token_cap_priority_over_interval():
    policy = BatchingPolicy(max_events=12, max_estimated_tokens=100, max_wait_seconds=10.0)
    state = _state(event_count=1, estimated_tokens=200, oldest_age_seconds=120.0)
    assert decide_flush(state, policy, batching_enabled=True) is FlushReason.TOKEN_CAP


def test_min_ready_events_lowers_the_event_count_trigger():
    """When the policy specifies min_ready_events, the bucket should flush as soon
    as that lower threshold is reached, even before max_events. This is what
    enables steady-state batching in the projection-claim path.
    """
    policy = BatchingPolicy(max_events=20, max_estimated_tokens=999_999, max_wait_seconds=999.0, min_ready_events=8)
    state = _state(event_count=8, estimated_tokens=10, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=True) is FlushReason.MAX_EVENTS


def test_min_ready_events_below_threshold_holds():
    policy = BatchingPolicy(max_events=20, max_estimated_tokens=999_999, max_wait_seconds=999.0, min_ready_events=8)
    state = _state(event_count=7, estimated_tokens=10, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=True) is None


def test_min_ready_events_defaults_to_max_events():
    """Omitting min_ready_events should keep prior behavior (threshold == max_events)."""
    policy = BatchingPolicy(max_events=12, max_estimated_tokens=999_999, max_wait_seconds=999.0)
    state = _state(event_count=11, estimated_tokens=10, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=True) is None
    state = _state(event_count=12, estimated_tokens=10, oldest_age_seconds=0.0)
    assert decide_flush(state, policy, batching_enabled=True) is FlushReason.MAX_EVENTS
