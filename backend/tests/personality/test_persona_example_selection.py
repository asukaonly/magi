"""P3.3: per-turn few-shot example selection by token overlap.

Previously ``PersonaTurnPlanner`` rendered the first 2 examples of the
chosen register regardless of what the user said. Personas authored with
5-7 examples per register saw the same two every turn, wasting the
remaining alignment material. This is a regression test for the lookup
that now ranks examples by token overlap against the user message.
"""

from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    "examples,message,expected",
    [
        (
            ["dinner noodles", "weather sunny", "memory leak detector", "code refactor"],
            "memory leak code",
            ["memory leak detector", "code refactor"],
        ),
        (
            ["今天晚饭吃面", "下雨记得带伞", "内存泄漏排查", "重构代码"],
            "内存泄漏代码",
            ["内存泄漏排查", "重构代码"],
        ),
    ],
)
def test_relevant_examples_outrank_initial_distractors(examples, message, expected):
    plan = PersonaTurnPlanner().build_plan(
        config=_config_with_examples(examples),
        user_message=message,
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples == expected


@pytest.mark.parametrize(
    "case_example_a,case_example_b,case_example_c,case_user_message",
    [
        pytest.param(
            "User: x\nAssistant: y",
            "User: a\nAssistant: b",
            "User: c\nAssistant: d",
            "something totally unrelated 中文也是 unrelated",
            id="no_overlap_falls_back_to_declaration_order",
        ),
        pytest.param("alpha", "beta", "gamma", "", id="empty_user_message_keeps_declaration_order"),
    ],
)
def test_unmatched_persona_examples_keep_declaration_order(
    case_example_a, case_example_b, case_example_c, case_user_message
) -> None:
    examples = [case_example_a, case_example_b, case_example_c]
    config = _config_with_examples(examples)
    plan = PersonaTurnPlanner().build_plan(
        config=config, user_message=case_user_message, scenario="chat", task_category="chat"
    )
    assert plan.selected_examples == examples[:2]


@pytest.mark.parametrize(
    "tied", [["code beta", "code alpha", "code gamma"], ["code gamma", "code beta", "code alpha"]]
)
def test_equal_relevance_preserves_declaration_order_after_ranking(tied):
    plan = PersonaTurnPlanner().build_plan(
        config=_config_with_examples(["dinner noodles", *tied]),
        user_message="code",
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples == tied[:2]


@pytest.mark.parametrize(
    "examples,expected",
    [
        ([], []),
        (["", "  "], []),
        (["one"], ["one"]),
        (["one", "two"], ["one", "two"]),
        (
            ["real example", "", "  ", "another real one", "third"],
            ["real example", "another real one"],
        ),
    ],
)
def test_example_filtering_and_cap(examples, expected):
    plan = PersonaTurnPlanner().build_plan(
        config=_config_with_examples(examples),
        user_message="unrelated",
        scenario="chat",
        task_category="chat",
    )
    assert plan.selected_examples == expected
