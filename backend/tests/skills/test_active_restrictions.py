"""Tests for the skill ``allowed-tools`` enforcement layer."""

from __future__ import annotations

import asyncio

import pytest

from magi.skills.active_restrictions import (
    current_restrictions,
    disallowed_reason,
    is_tool_allowed,
    push_restriction,
    pop_restriction,
    skill_restriction,
)


def test_no_restriction_allows_everything():
    assert current_restrictions() == ()
    assert is_tool_allowed("anything")
    assert disallowed_reason("anything") is None


def test_push_and_check():
    token = push_restriction({"Bash", "Read"})
    try:
        assert is_tool_allowed("Bash")
        assert is_tool_allowed("Read")
        assert not is_tool_allowed("Write")
        reason = disallowed_reason("Write")
        assert reason is not None
        assert "allowed-tools" in reason
    finally:
        pop_restriction(token)
    # State restored after pop.
    assert is_tool_allowed("Write")


def test_nested_restrictions_intersect():
    with skill_restriction({"Bash", "Read", "Write"}):
        with skill_restriction({"Bash", "Read"}):
            assert is_tool_allowed("Bash")
            assert is_tool_allowed("Read")
            # 'Write' is in the outer set but not the inner — must be blocked.
            assert not is_tool_allowed("Write")
        # After inner pops, outer set governs again.
        assert is_tool_allowed("Write")


def test_none_allowed_tools_is_noop():
    token = push_restriction(None)
    try:
        assert is_tool_allowed("anything")
    finally:
        pop_restriction(token)


@pytest.mark.asyncio
async def test_restriction_propagates_into_child_task():
    """A child awaited inside the same task sees the restriction; a sibling task does not."""
    seen_in_child = []
    seen_in_sibling = []

    async def child():
        seen_in_child.append(is_tool_allowed("Forbidden"))

    async def sibling():
        # asyncio.create_task captures the current context at scheduling
        # time, so this task DOES inherit the push by default.
        seen_in_sibling.append(is_tool_allowed("Forbidden"))

    with skill_restriction({"Bash"}):
        await child()
        task = asyncio.create_task(sibling())
        await task

    assert seen_in_child == [False]
    # create_task inherits the contextvar snapshot — both children see deny.
    assert seen_in_sibling == [False]


def test_disallowed_reason_truncates_long_list():
    big = {f"tool_{i}" for i in range(20)}
    with skill_restriction(big):
        reason = disallowed_reason("missing")
        assert reason is not None
        assert "(+15 more)" in reason
