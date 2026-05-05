from __future__ import annotations

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    ToolInvocationCompleted, TaskContext, ToolError,
    UserMessageReceived, AssistantResponseProduced, SensorEventEmitted,
)
from magi.memory.event_translation import translate


def test_tool_invocation_completed_to_action_executed():
    payload = ToolInvocationCompleted(
        tool_name="shell", tool_category="external_tool",
        success=True, duration_ms=12.5,
        started_at=1.0, finished_at=2.0,
        args_summary="ls -la", result_summary="ok",
        error=None,
        context=TaskContext("sess-1", "turn-1", "task-1", "user-1"),
    )
    ev = Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload, correlation_id="c1")
    me = translate(ev)
    assert me is not None
    assert me.event_type == EventTypes.ACTION_EXECUTED
    assert me.source_item_id == "shell"
    assert me.session_id == "sess-1"
    assert me.task_id == "task-1"
    assert me.user_id == "user-1"
    assert me.metadata_json is not None
    assert me.metadata_json["duration_ms"] == 12.5
    assert me.metadata_json["input"] == "ls -la"
    assert me.metadata_json["output"] == "ok"
    assert me.correlation_id == "c1"


def test_tool_invocation_failure_marks_higher_level_and_records_error():
    err = ToolError(type="ValueError", message="boom")
    payload = ToolInvocationCompleted(
        tool_name="shell", tool_category="external_tool",
        success=False, duration_ms=1.0,
        started_at=1.0, finished_at=2.0,
        args_summary="x", result_summary=None, error=err,
        context=TaskContext("s", "t", None, None),
    )
    me = translate(Event(type=EventTypes.TOOL_INVOCATION_COMPLETED, data=payload))
    assert me is not None
    assert me.level >= 3
    assert me.metadata_json["error"] == "boom"


def test_user_message_received_translation():
    payload = UserMessageReceived(
        content="hi",
        context=TaskContext("s", "t", None, "u"),
        metadata={"author_type": "user"},
    )
    me = translate(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))
    assert me is not None
    assert me.event_type == EventTypes.USER_MESSAGE
    assert me.content == "hi"
    assert me.session_id == "s"
    assert me.user_id == "u"


def test_assistant_response_produced_translation():
    payload = AssistantResponseProduced(
        content="reply",
        context=TaskContext("s", "t", None, "u"),
    )
    me = translate(Event(type=EventTypes.ASSISTANT_RESPONSE_PRODUCED, data=payload))
    assert me is not None
    assert me.event_type == EventTypes.AI_RESPONSE
    assert me.content == "reply"


def test_sensor_event_emitted_translation():
    payload = SensorEventEmitted(
        sensor_name="screen_time",
        payload={"app": "chrome", "duration": 60},
        context=TaskContext(None, None, None, "u"),
    )
    me = translate(Event(type=EventTypes.SENSOR_EVENT_EMITTED, data=payload))
    assert me is not None
    assert me.event_type == "SENSOR_EVENT"


def test_unknown_event_type_returns_none():
    me = translate(Event(type="NeverHeardOf", data=None))
    assert me is None


def test_legacy_event_passthrough():
    """If a legacy-type Event with dict data is passed in, translate should
    delegate to normalize_runtime_event directly (no double-translation)."""
    ev = Event(
        type=EventTypes.USER_MESSAGE,
        data={"content": "hi", "session_id": "s", "user_id": "u"},
    )
    me = translate(ev)
    assert me is not None
    assert me.event_type == EventTypes.USER_MESSAGE
    assert me.content == "hi"
