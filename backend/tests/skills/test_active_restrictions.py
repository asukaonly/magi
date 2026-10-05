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


@pytest.mark.parametrize(
    "rule,allowed,denied",
    [
        ("Bash(git add *)", "git add foo.txt", "git commit -m hi"),
        ("Bash(agent-browser:*)", "agent-browser:run --headless", "rm -rf /"),
        ("Bash(npx agent-browser:*)", "npx agent-browser:test", "agent-browser:test"),
    ],
)
def test_command_patterns_preserve_literal_colons(rule, allowed, denied):
    with skill_preapproval([rule]):
        assert is_call_preapproved("Bash", {"command": allowed})
        assert not is_call_preapproved("Bash", {"command": denied})
        assert not is_call_preapproved("Other", {"command": allowed})


def test_stacked_frames_union():
    """If any active frame pre-approves, the call is pre-approved."""
    with skill_preapproval(["Read"]):
        with skill_preapproval(["Bash(git *)"]):
            # Inner frame approves Bash(git ...), outer frame approves any Read.
            assert is_call_preapproved("Read", {"path": "/x"})
            assert is_call_preapproved("Bash", {"command": "git status"})
            # Nothing approves Write.
            assert not is_call_preapproved("Write", {"path": "/x"})


@pytest.mark.parametrize(
    "rules", [["Bash(git *)", "Bash(git commit *)"], ["Bash(git commit *)", "Bash(git *)"]]
)
def test_matched_rule_returns_first_overlapping_match(rules):
    with skill_preapproval(rules):
        rule = matched_rule("Bash", {"command": "git commit -m x"})
        assert rule is not None and rule.display == rules[0]


@pytest.mark.parametrize("rules", [None, []])
def test_empty_rules_preserve_existing_preapproval(rules):
    with skill_preapproval(["Read"]):
        token = push_skill_rules(rules)
        try:
            assert is_call_preapproved("Read", {"path": "anything"})
            assert not is_call_preapproved("Bash", {"command": "anything"})
        finally:
            pop_skill_rules(token)
        assert is_call_preapproved("Read", {})
    assert current_preapproval_frames() == ()


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
