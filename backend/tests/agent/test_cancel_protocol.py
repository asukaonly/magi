from __future__ import annotations

import pytest

from magi.chat.task_agent.cancel_protocol import (
    is_strict_cancel_text,
    load_strict_cancel_phrases,
)


@pytest.mark.parametrize(
    "user_text",
    [
        "stop",
        "Stop!",
        "cancel",
        "abort",
        "never mind",
        "don't do that",
        "取消",
        "停止！",
        "停一下",
        "算了吧。",
        "不用做了",
    ],
)
def test_strict_cancel_accepts_complete_control_phrases(user_text: str) -> None:
    assert is_strict_cancel_text(user_text) is True


@pytest.mark.parametrize(
    "user_text",
    [
        "Please don't stop at login; continue to checkout.",
        "Can you cancel the trailing whitespace in this diff?",
        "Use abort-on-error behavior in the script.",
        "把这个取消订阅按钮改一下",
        "先停留在这个页面看一下",
        "搞错了，应该使用 Python",
        "Nope, choose the second option",
        "",
        "   ",
        "？？？",
    ],
)
def test_strict_cancel_rejects_task_content_and_interaction_answers(
    user_text: str,
) -> None:
    assert is_strict_cancel_text(user_text) is False


def test_strict_cancel_phrases_are_loaded_from_yaml() -> None:
    phrases = load_strict_cancel_phrases()

    assert "stop" in phrases
    assert "取消" in phrases
    assert isinstance(phrases, frozenset)
