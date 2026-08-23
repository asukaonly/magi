"""Unit tests for derive_execution_shape (ADR-0005, three-state orchestration)."""
from __future__ import annotations

from magi.chat.task_agent.execution_shape import derive_execution_shape


def test_none_without_tools_is_reply() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, orchestration="none", has_tools=False
        )
        == "reply"
    )


def test_none_with_tools_is_tool_loop() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, orchestration="none", has_tools=True
        )
        == "tool_loop"
    )


def test_required_is_plan_fanout_even_without_tools() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, orchestration="required", has_tools=True
        )
        == "plan_fanout"
    )
    assert (
        derive_execution_shape(
            has_image_attachments=False, orchestration="required", has_tools=False
        )
        == "plan_fanout"
    )


def test_maybe_uses_selected_tools_to_choose_execution_shape() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, orchestration="maybe", has_tools=False
        )
        == "reply"
    )
    assert (
        derive_execution_shape(
            has_image_attachments=False, orchestration="maybe", has_tools=True
        )
        == "tool_loop"
    )


def test_image_forces_reply_over_everything() -> None:
    for orch in ("none", "maybe", "required"):
        assert (
            derive_execution_shape(
                has_image_attachments=True, orchestration=orch, has_tools=True
            )
            == "reply"
        )
