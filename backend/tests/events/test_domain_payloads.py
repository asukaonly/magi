from __future__ import annotations
from magi.events.domain_payloads import (
    TaskContext,
    ToolError,
    UserMessageReceived,
)


def test_tool_error_truncated_default_false():
    err = ToolError(type="ValueError", message="boom")
    assert err.truncated is False


def test_user_message_received_metadata_default_empty():
    payload = UserMessageReceived(
        content="hi",
        context=TaskContext(session_id="s", turn_id="t", task_id=None, user_id="u"),
    )
    assert payload.metadata == {}
