from __future__ import annotations

import pytest

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


def test_additive_context_with_causal_detail_augment_when_step_is_idle() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="The error only happens after refresh.",
        )
    )

    assert disposition == InterruptionDisposition.AUGMENT


def test_additive_context_with_targeting_detail_augment_when_step_is_idle() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="Use the staging endpoint.",
        )
    )

    assert disposition == InterruptionDisposition.AUGMENT


def test_additive_refinement_with_instead_does_not_interrupt() -> None:
    classifier = InterruptionClassifier()

    disposition = classifier.classify(
        InterruptionContext(
            user_text="Also, return JSON instead of YAML.",
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


@pytest.mark.asyncio
async def test_async_classifier_uses_fast_model_for_chinese_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = InterruptionClassifier(llm_pool=object())

    async def _fake_call(*, system_prompt, messages, disable_thinking, json_mode, timeout_seconds):  # type: ignore[no-untyped-def]
        assert "interrupt" in system_prompt
        assert disable_thinking is True
        assert json_mode is True
        assert timeout_seconds == 8.0
        assert messages == [
            {
                "role": "user",
                "content": '{"active_request": "看下目前的项目文档和规划", "pending_user_messages": ["补充一下，顺便看下接口"], "new_user_message": "搞错了，不用做了"}',
            }
        ]
        return '{"disposition":"interrupt"}'

    monkeypatch.setattr(classifier, "_can_use_model_classifier", lambda: True)
    monkeypatch.setattr(classifier._llm_service, "call", _fake_call)

    disposition = await classifier.aclassify(
        InterruptionContext(
            user_text="搞错了，不用做了",
            root_user_message="看下目前的项目文档和规划",
            pending_turns=["补充一下，顺便看下接口"],
        )
    )

    assert disposition == InterruptionDisposition.INTERRUPT
