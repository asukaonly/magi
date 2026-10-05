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


def test_persisted_nondefault_reasoning_policy_controls_escalation_after_restore():
    import json
    from magi.config.models import ThinkingDepth

    policy = ReasoningPolicy(
        preference=ReasoningPreference.FAST,
        initial_depth=ThinkingDepth.NONE,
        maximum_depth=ThinkingDepth.HIGH,
        max_escalations=3,
        escalation_step=1,
    )
    expected = {
        "preference": "fast",
        "initial_depth": "none",
        "maximum_depth": "high",
        "max_escalations": 3,
        "escalation_step": 1,
    }
    assert policy.to_dict() == expected
    restored = ReasoningPolicy.from_dict(json.loads(json.dumps(expected)))
    assert restored == policy
    state = ReasoningState.start(restored)
    assert state.requested_depth is ThinkingDepth.NONE
    for expected_depth in (ThinkingDepth.LOW, ThinkingDepth.MEDIUM, ThinkingDepth.HIGH):
        assert state.escalate(restored, reason="validation_failed") is True
        assert state.requested_depth is expected_depth
    assert state.escalate(restored, reason="validation_failed") is False
    assert state.escalation_count == 3
