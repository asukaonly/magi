"""Regression coverage for conservative user-cue example selection."""

from __future__ import annotations

import pytest

from magi.personality.loader import PersonalityConfig, Register
from magi.personality.turn_planner import PersonaTurnPlanner


def _example(user: str, reply: str = "A suitable reply.") -> str:
    return f"[User: {user}]\nSeven: {reply}"


def _select(examples: list[str], message: str) -> list[str]:
    config = PersonalityConfig(
        name="七号", registers={"chat": Register(behavior="chat", examples=examples)}
    )
    return PersonaTurnPlanner().build_plan(
        config=config, user_message=message, scenario="chat", task_category="chat"
    ).selected_examples


@pytest.mark.parametrize(
    "cues,message,expected_indices",
    [
        (["dinner noodles", "weather sunny", "memory leak detector"], "memory leak", [2]),
        (["今天晚饭吃面", "下雨记得带伞", "内存泄漏排查"], "内存泄漏", [2]),
        (["摸鱼", "我回来了"], "回来了", [1]),
        (["哦", "晚安"], "哦。", [0]),
        (["哦", "晚安"], "晚安啦", [1]),
        (["hi", "bye"], "HI!", [0]),
    ],
)
def test_selects_similar_user_cues(cues, message, expected_indices):
    examples = [_example(cue) for cue in cues]
    assert _select(examples, message) == [examples[index] for index in expected_indices]


@pytest.mark.parametrize("message", ["", "...", "晚安", "哦", "我今天面试过了"])
@pytest.mark.parametrize("count", [1, 2, 3])
def test_no_match_stays_empty_even_with_fewer_examples_than_limit(message, count):
    examples = [
        _example("今天只想摸鱼，完全不想动。"),
        _example("这个 APP 弹窗也太多了。"),
        _example("你说话好人机啊"),
    ]
    assert _select(examples[:count], message) == []


def test_does_not_match_assistant_reply_or_bad_example_text():
    distractor = "[User: Lunch?]\nBad: memory leak\nGood: memory leak detector"
    relevant = _example("memory leak", "Let's inspect allocations.")
    assert _select([distractor, relevant], "memory leak") == [relevant]


def test_does_not_fill_remaining_slots_with_unrelated_examples():
    relevant = _example("我回来了", "回来啦。")
    assert _select([_example("dinner"), relevant], "我回来了") == [relevant]


def test_exact_cue_outranks_partial_match_and_ties_keep_declaration_order():
    partial = _example("memory leak detector")
    first = _example("memory leak", "First reply.")
    second = _example("memory leak", "Second reply.")
    assert _select([partial, first, second], "memory leak") == [first, second]


@pytest.mark.parametrize(
    "example", ["", "  ", "memory leak", "[User: memory leak]", "[User: memory leak]\n  "]
)
def test_skips_examples_without_a_complete_user_reply_block(example):
    assert _select([example], "memory leak") == []


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limit_selects_nothing(limit):
    register = Register(examples=[_example("hi")])
    assert PersonaTurnPlanner._select_examples(register=register, user_message="hi", limit=limit) == []
