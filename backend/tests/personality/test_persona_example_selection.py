"""P3.3: per-turn few-shot example selection by token overlap.

Previously ``PersonaTurnPlanner`` rendered the first 2 examples of the
chosen register regardless of what the user said. Personas authored with
5-7 examples per register saw the same two every turn, wasting the
remaining alignment material. This is a regression test for the lookup
that now ranks examples by token overlap against the user message.
"""

from __future__ import annotations

from magi.personality.loader import PersonalityConfig, Register
from magi.personality.turn_planner import PersonaTurnPlanner


def _config_with_examples(examples: list[str]) -> PersonalityConfig:
    return PersonalityConfig(
        name="七号",
        registers={
            "chat": Register(
                description="chat",
                behavior="chat",
                examples=examples,
            ),
        },
    )


def test_fewer_examples_than_limit_returns_all() -> None:
    config = _config_with_examples(["one", "two"])
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="anything",
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples == ["one", "two"]


def test_picks_examples_with_overlapping_tokens() -> None:
    config = _config_with_examples([
        "User: 怎么修复内存泄漏\nAssistant: 先用 leak detector 跑一遍",
        "User: 今天晚饭吃什么\nAssistant: 吃面",
        "User: 这代码太烂了\nAssistant: 重构一下",
        "User: 心情不好\nAssistant: 抱抱",
        "User: 你最近怎么样\nAssistant: 还行",
        "User: 帮我写个脚本\nAssistant: 行",
    ])
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="帮我修一下内存泄漏的代码",
        scenario="chat",
        task_category="chat",
    )

    # The 内存泄漏 / 代码 examples should win against unrelated ones.
    assert "内存泄漏" in plan.selected_examples[0] or "代码" in plan.selected_examples[0]


def test_no_overlap_falls_back_to_declaration_order() -> None:
    examples = [
        "User: x\nAssistant: y",
        "User: a\nAssistant: b",
        "User: c\nAssistant: d",
    ]
    config = _config_with_examples(examples)
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="something totally unrelated 中文也是 unrelated",
        scenario="chat",
        task_category="chat",
    )
    # No overlap → first 2 by declaration order.
    assert plan.selected_examples == examples[:2]


def test_empty_user_message_keeps_declaration_order() -> None:
    examples = [
        "alpha",
        "beta",
        "gamma",
    ]
    config = _config_with_examples(examples)
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="",
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples == examples[:2]


def test_ties_broken_by_declaration_order() -> None:
    """When two examples share the same overlap with the user message,
    the earlier declared one wins. This keeps the result deterministic."""
    config = _config_with_examples([
        "User: 代码很乱\nAssistant: 重构",
        "User: 代码逻辑不清\nAssistant: 拆函数",
        "User: 完全不相关\nAssistant: 嗯",
    ])
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="代码看上去有问题",
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples[0] == "User: 代码很乱\nAssistant: 重构"


def test_filters_empty_and_whitespace_examples() -> None:
    config = _config_with_examples([
        "real example",
        "",
        "   ",
        "another real one",
    ])
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="anything",
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples == ["real example", "another real one"]


def test_caps_at_two_by_default() -> None:
    config = _config_with_examples(["a one", "b two", "c three", "d four"])
    plan = PersonaTurnPlanner().build_plan(
        config=config,
        user_message="any text",
        scenario="chat",
        task_category="chat",
    )
    assert len(plan.selected_examples) <= 2
