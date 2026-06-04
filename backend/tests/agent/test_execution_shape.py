"""Unit tests for derive_execution_shape (ADR-0005).

Execution shape is a pure function of semantic signals, not an LLM-emitted
field. These tests pin the derivation table so graph_shape can never again
contradict the tool list.
"""
from __future__ import annotations

from magi.chat.task_agent.execution_shape import derive_execution_shape


def test_no_tools_no_orchestration_is_reply() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, needs_orchestration=False, has_tools=False
        )
        == "reply"
    )


def test_tools_without_orchestration_is_tool_loop() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, needs_orchestration=False, has_tools=True
        )
        == "tool_loop"
    )


def test_orchestration_is_plan_fanout() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, needs_orchestration=True, has_tools=True
        )
        == "plan_fanout"
    )


def test_orchestration_wins_even_without_tools() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=False, needs_orchestration=True, has_tools=False
        )
        == "plan_fanout"
    )


def test_image_forces_reply_even_with_tools() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=True, needs_orchestration=False, has_tools=True
        )
        == "reply"
    )


def test_image_takes_precedence_over_orchestration() -> None:
    assert (
        derive_execution_shape(
            has_image_attachments=True, needs_orchestration=True, has_tools=True
        )
        == "reply"
    )
