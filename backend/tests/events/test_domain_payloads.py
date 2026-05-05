from __future__ import annotations
import pytest
from magi.events.domain_payloads import (
    TaskContext,
    ToolError,
    ToolInvocationCompleted,
    TaskStarted,
    TaskCompleted,
    TaskFailed,
    UserMessageReceived,
    AssistantResponseProduced,
    SensorEventEmitted,
)


def test_tool_error_truncated_default_false():
    err = ToolError(type="ValueError", message="boom")
    assert err.truncated is False


def test_tool_invocation_completed_is_frozen():
    payload = ToolInvocationCompleted(
        tool_name="shell",
        tool_category="external_tool",
        success=True,
        duration_ms=12.5,
        started_at=1.0,
        finished_at=2.0,
        args_summary="ls",
        result_summary="ok",
        error=None,
        context=TaskContext(session_id="s", turn_id="t", task_id=None, user_id=None),
    )
    with pytest.raises(Exception):
        payload.tool_name = "x"  # frozen


def test_task_failed_requires_error():
    err = ToolError(type="X", message="m")
    payload = TaskFailed(
        task_id="t1", task_type="explore",
        started_at=1.0, finished_at=2.0,
        error=err,
        context=TaskContext(session_id=None, turn_id=None, task_id="t1", user_id=None),
    )
    assert payload.error is err


def test_user_message_received_metadata_default_empty():
    payload = UserMessageReceived(
        content="hi",
        context=TaskContext(session_id="s", turn_id="t", task_id=None, user_id="u"),
    )
    assert payload.metadata == {}
