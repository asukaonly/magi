from __future__ import annotations

from magi.agent.execution.reasoning import (
    ReasoningPolicy,
    ReasoningPreference,
    ReasoningState,
)


def test_auto_moves_from_low_to_high_to_max() -> None:
    policy = ReasoningPolicy.from_preference(ReasoningPreference.AUTO)
    state = ReasoningState.start(policy)

    assert state.requested_depth.value == "low"
    assert state.escalate(policy, reason="task_complexity") is True
    assert state.requested_depth.value == "high"
    assert state.escalate(policy, reason="validation_failed") is True
    assert state.requested_depth.value == "max"
    assert state.escalate(policy, reason="stalled_reasoning") is False
    assert state.escalation_count == 2


def test_fast_and_deep_keep_single_level_escalations() -> None:
    fast_policy = ReasoningPolicy.from_preference(ReasoningPreference.FAST)
    fast_state = ReasoningState.start(fast_policy)
    assert fast_state.escalate(fast_policy, reason="task_complexity") is True
    assert fast_state.requested_depth.value == "low"
    assert fast_state.escalate(fast_policy, reason="stalled_reasoning") is False

    deep_policy = ReasoningPolicy.from_preference(ReasoningPreference.DEEP)
    deep_state = ReasoningState.start(deep_policy)
    assert deep_state.escalate(deep_policy, reason="task_complexity") is True
    assert deep_state.requested_depth.value == "high"
    assert deep_state.escalate(deep_policy, reason="validation_failed") is True
    assert deep_state.requested_depth.value == "max"


def test_reasoning_policy_round_trip_preserves_escalation_step() -> None:
    policy = ReasoningPolicy.from_preference(ReasoningPreference.AUTO)

    assert ReasoningPolicy.from_dict(policy.to_dict()) == policy
    assert policy.escalation_step == 2
