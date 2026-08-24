from __future__ import annotations

import pytest

from magi.chat.task_agent.interruption_classifier import (
    InterruptionClassifier,
    InterruptionContext,
    InterruptionDisposition,
    StepState,
)


class TestSyncClassify:
    """The synchronous classifier is intentionally narrow.

    AUGMENT/STEER and non-strict INTERRUPT decisions belong to the LLM
    path; the sync classifier only makes calls it can be confident
    about.
    """

    def test_strict_cancel_is_interrupt(self) -> None:
        classifier = InterruptionClassifier()
        assert (
            classifier.classify(InterruptionContext(user_text="stop"))
            == InterruptionDisposition.INTERRUPT
        )

    def test_strict_cancel_chinese(self) -> None:
        classifier = InterruptionClassifier()
        assert (
            classifier.classify(InterruptionContext(user_text="不用做了"))
            == InterruptionDisposition.INTERRUPT
        )

    def test_long_message_with_passing_cancel_keyword_steers(self) -> None:
        classifier = InterruptionClassifier()
        disposition = classifier.classify(
            InterruptionContext(
                user_text="Please stop and change the goal to fixing the login flow.",
            )
        )
        assert disposition == InterruptionDisposition.STEER

    def test_additive_context_steers_without_auxiliary_model(self) -> None:
        classifier = InterruptionClassifier()
        for text in (
            "Also, the API error only happens on mobile.",
            "The error only happens after refresh.",
            "Use the staging endpoint.",
            "Also, return JSON instead of YAML.",
        ):
            assert classifier.classify(InterruptionContext(user_text=text)) == (
                InterruptionDisposition.STEER
            )

    def test_atomic_step_state_defers_strict_cancel(self) -> None:
        classifier = InterruptionClassifier()
        assert (
            classifier.classify(
                InterruptionContext(
                    user_text="stop",
                    step_state=StepState(atomic=True),
                )
            )
            == InterruptionDisposition.DEFER
        )

    def test_side_effecting_step_state_defers_strict_cancel(self) -> None:
        classifier = InterruptionClassifier()
        assert (
            classifier.classify(
                InterruptionContext(
                    user_text="stop",
                    step_state=StepState(side_effecting=True),
                )
            )
            == InterruptionDisposition.DEFER
        )


@pytest.mark.asyncio
async def test_async_classifier_uses_the_same_deterministic_policy() -> None:
    classifier = InterruptionClassifier()
    disposition = await classifier.aclassify(
        InterruptionContext(
            user_text="搞错了，不用做了",
            root_user_message="看下目前的项目文档和规划",
            pending_turns=["补充一下，顺便看下接口"],
        )
    )

    assert disposition == InterruptionDisposition.INTERRUPT


@pytest.mark.parametrize(
    "user_text",
    [
        "stop",
        "Stop!",
        "STOP.",
        "stop, ",
        "Cancel",
        "cancel!",
        "abort",
        "Nope.",
        "never mind",
        "Never  mind!",
        "don't do that",
        "Don't do that!",
        "取消",
        "取消！",
        "停止",
        "停一下",
        "算了",
        "算了吧。",
        "搞错了",
        "不用做了",
    ],
)
def test_strict_interrupt_accepts_canonical_cancel_phrases(user_text: str) -> None:
    classifier = InterruptionClassifier()

    assert classifier.looks_like_strict_interrupt(user_text) is True


@pytest.mark.parametrize(
    "user_text",
    [
        # Substrings of cancel keywords must NOT trigger.
        "Please don't stop at the login page, also check checkout.",
        "Can you cancel the trailing whitespace in this diff?",
        "I want to abort early if X, but continue if Y.",
        "Use the staging endpoint instead of prod.",
        "顺便看看 github 的仓库",
        "把这个取消订阅按钮改一下",
        "先停留在这个页面看一下",
        # Empty / whitespace.
        "",
        "   ",
        "？？？",
    ],
)
def test_strict_interrupt_rejects_non_cancel_messages(user_text: str) -> None:
    classifier = InterruptionClassifier()

    assert classifier.looks_like_strict_interrupt(user_text) is False


def test_strict_interrupt_phrases_loaded_from_yaml() -> None:
    """The cancel phrase set is sourced from interruption_phrases.yaml."""
    from magi.chat.task_agent.interruption_classifier import (
        _load_strict_interrupt_phrases,
    )

    phrases = _load_strict_interrupt_phrases()
    # Sanity check both en and zh buckets contributed entries.
    assert "stop" in phrases
    assert "取消" in phrases
    # Anything we add later via YAML should automatically reach the set.
    assert isinstance(phrases, frozenset)
