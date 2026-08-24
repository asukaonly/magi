"""Tests for the skill ``allowed-tools`` pre-approval layer.

Per the Claude Code Skills spec, ``allowed-tools`` *grants* permission
to matching calls (skipping the permission prompt). It does *not*
restrict tool availability. These tests check that semantic.
"""

from __future__ import annotations

import asyncio

import pytest

from magi.skills.active_restrictions import (
    current_preapproval_frames,
    is_call_preapproved,
    matched_rule,
    push_skill_rules,
    pop_skill_rules,
    skill_preapproval,
)
from magi.skills.allowed_tools_rules import ToolRule


# ---------------------------------------------------------------------------
# Core pre-approval semantics
# ---------------------------------------------------------------------------


def test_no_active_frames_means_nothing_preapproved():
    assert current_preapproval_frames() == ()
    assert not is_call_preapproved("Bash", {"command": "rm -rf /"})
    assert matched_rule("Bash", {}) is None


def test_bare_rule_preapproves_any_call_to_that_tool():
    with skill_preapproval(["Read"]):
        assert is_call_preapproved("Read", {"path": "/anything"})
        # Tool name mismatch — not pre-approved.
        assert not is_call_preapproved("Write", {"path": "/anything"})


def test_pattern_rule_matches_bash_command():
    with skill_preapproval(["Bash(git add *)"]):
        assert is_call_preapproved("Bash", {"command": "git add foo.txt"})
        assert not is_call_preapproved("Bash", {"command": "git commit -m hi"})


def test_pattern_rule_with_colon_pattern():
    """Reproduce the ``agent-browser`` case from the wild."""
    with skill_preapproval(
        ["Bash(agent-browser:*)", "Bash(npx agent-browser:*)"]
    ):
        assert is_call_preapproved("Bash", {"command": "agent-browser:run --headless"})
        assert is_call_preapproved("Bash", {"command": "npx agent-browser:test"})
        assert not is_call_preapproved("Bash", {"command": "rm -rf /"})


def test_stacked_frames_union():
    """If any active frame pre-approves, the call is pre-approved."""
    with skill_preapproval(["Read"]):
        with skill_preapproval(["Bash(git *)"]):
            # Inner frame approves Bash(git ...), outer frame approves any Read.
            assert is_call_preapproved("Read", {"path": "/x"})
            assert is_call_preapproved("Bash", {"command": "git status"})
            # Nothing approves Write.
            assert not is_call_preapproved("Write", {"path": "/x"})


def test_matched_rule_returns_first_match():
    with skill_preapproval(["Bash(git add *)", "Bash(git commit *)"]):
        rule = matched_rule("Bash", {"command": "git commit -m x"})
        assert rule is not None
        assert rule.display == "Bash(git commit *)"


def test_none_rules_is_noop():
    token = push_skill_rules(None)
    try:
        assert not is_call_preapproved("Bash", {"command": "anything"})
    finally:
        pop_skill_rules(token)


def test_empty_list_is_noop():
    token = push_skill_rules([])
    try:
        assert not is_call_preapproved("Read", {})
    finally:
        pop_skill_rules(token)


def test_accepts_toolrule_objects_directly():
    rule = ToolRule(tool="Read", pattern="src/*")
    with skill_preapproval([rule]):
        assert is_call_preapproved("Read", {"path": "src/main.py"})
        assert not is_call_preapproved("Read", {"path": "tests/test.py"})


# ---------------------------------------------------------------------------
# Contextvar lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preapproval_propagates_into_awaited_child_and_task():
    seen_child = []
    seen_sibling = []

    async def child():
        seen_child.append(is_call_preapproved("Bash", {"command": "anything"}))

    async def sibling():
        seen_sibling.append(is_call_preapproved("Bash", {"command": "anything"}))

    with skill_preapproval(["Bash"]):
        await child()
        await asyncio.create_task(sibling())

    assert seen_child == [True]
    # create_task inherits the contextvar snapshot.
    assert seen_sibling == [True]
