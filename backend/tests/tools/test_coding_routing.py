"""Tests for Coding routing in context_routing.orchestration."""
from __future__ import annotations

import pytest

from magi.tools.context_routing.orchestration import (
    default_orchestration_strategy,
    normalize_orchestration_strategy,
)


def test_normalize_keeps_coding_default_leaf_type() -> None:
    payload = {
        "mode": "direct",
        "planner": "task_agent",
        "default_leaf_type": "Coding",
        "allow_parallel": False,
    }
    out = normalize_orchestration_strategy(payload)
    assert out["default_leaf_type"] == "Coding"
    assert out["mode"] == "direct"
    assert out["planner"] == "task_agent"
    assert out["allow_parallel"] is False


def test_normalize_still_rejects_unknown_leaf_type() -> None:
    payload = {
        "mode": "direct",
        "planner": "task_agent",
        "default_leaf_type": "WatNotALeaf",
        "allow_parallel": False,
    }
    out = normalize_orchestration_strategy(payload)
    assert out["default_leaf_type"] == "general-purpose"


def test_normalize_still_keeps_explore_and_general() -> None:
    for leaf in ("Explore", "general-purpose"):
        out = normalize_orchestration_strategy({"default_leaf_type": leaf})
        assert out["default_leaf_type"] == leaf


@pytest.mark.parametrize("phrase", [
    "fix bug in src/auth.py",
    "fix this bug",
    "refactor the connect helper",
    "add a function called retry()",
    "rename foo to bar across these files",
    "改一下 config.py 里的默认值",
    "修一下这个 bug",
    "重构 connect()",
    "加一个函数 retry",
    "修复 connect 函数的 race condition",
])
def test_default_strategy_picks_coding_when_agent_recommended(phrase: str) -> None:
    out = default_orchestration_strategy(
        tools=["agent", "file_edit"],
        user_lower=phrase.lower(),
    )
    assert out["default_leaf_type"] == "Coding", f"phrase {phrase!r} -> {out}"
    assert out["mode"] == "direct"
    assert out["planner"] == "task_agent"
    assert out["allow_parallel"] is False


@pytest.mark.parametrize("phrase", [
    "fix this bug",
    "改一下这个函数",
])
def test_coding_branch_requires_agent_in_tools(phrase: str) -> None:
    """Coding routing only kicks in when the chat agent has the agent tool;
    otherwise we fall through to general-purpose so the LLM uses direct edits."""
    out = default_orchestration_strategy(
        tools=["file_edit", "file_read"],
        user_lower=phrase.lower(),
    )
    assert out["default_leaf_type"] == "general-purpose"


def test_existing_explore_branch_still_routes_explore() -> None:
    out = default_orchestration_strategy(
        tools=["agent"],
        user_lower="please scan the codebase for unused imports",
    )
    assert out["default_leaf_type"] == "Explore"


def test_existing_architecture_branch_still_routes_explore() -> None:
    out = default_orchestration_strategy(
        tools=["agent"],
        user_lower="walk me through the architecture of this repo",
    )
    assert out["default_leaf_type"] == "Explore"


def test_neutral_chat_falls_through_to_general() -> None:
    out = default_orchestration_strategy(
        tools=["agent"],
        user_lower="hey what's up",
    )
    assert out["default_leaf_type"] == "general-purpose"


def test_system_prompt_advertises_coding_in_schema() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT
    assert "Coding" in CONTEXT_DECIDER_SYSTEM_PROMPT
    assert '"default_leaf_type": "Explore|general-purpose|Coding"' in CONTEXT_DECIDER_SYSTEM_PROMPT


def test_system_prompt_has_coding_few_shot() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT
    assert '"default_leaf_type": "Coding"' in CONTEXT_DECIDER_SYSTEM_PROMPT
    coding_blocks = [
        block
        for block in CONTEXT_DECIDER_SYSTEM_PROMPT.split("\n\n")
        if '"default_leaf_type": "Coding"' in block
    ]
    assert coding_blocks, "no Coding few-shot found"
    for block in coding_blocks:
        assert '"agent"' in block, f"Coding few-shot must include agent tool: {block!r}"
