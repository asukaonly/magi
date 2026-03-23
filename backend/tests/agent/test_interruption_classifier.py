from __future__ import annotations

from magi.agent.task_agents.chat.interruption_classifier import (
    InterruptionClassifier,
    InterruptionContext,
    InterruptionDisposition,
    StepState,
)


def test_explicit_stop_or_change_goal_text_interrupts_when_step_is_idle() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="Please stop and change the goal to fixing the login flow.",
        )
    )

    assert disposition == InterruptionDisposition.INTERRUPT


def test_additive_context_text_augment_when_step_is_idle() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="Also, the API error only happens on mobile.",
        )
    )

    assert disposition == InterruptionDisposition.AUGMENT


def test_atomic_or_side_effecting_step_state_defers_interrupting_text() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="Stop and change the goal to a different task.",
            step_state=StepState(atomic=True),
        )
    )

    assert disposition == InterruptionDisposition.DEFER


def test_side_effecting_step_state_defers_interrupting_text() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="Please stop and change the goal to a different task.",
            step_state=StepState(side_effecting=True),
        )
    )

    assert disposition == InterruptionDisposition.DEFER
