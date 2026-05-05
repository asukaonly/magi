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


def test_span_completed_tool_invocation_translates_like_legacy():
    from magi.events.domain_payloads import SpanCompleted
    sp = SpanCompleted(
        span_id="s1", trace_id="t1", parent_span_id=None,
        node_type="tool_invocation", name="shell", status="ok",
        started_at_ms=1000, ended_at_ms=1150, duration_ms=150,
        error=None, result_preview="ok", turn_id="turn-1",
        attributes={
            "tool_name": "shell",
            "tool_category": "external_tool",
            "success": True,
            "execution_time_ms": 150,
            "started_at": 1.0,
            "finished_at": 2.0,
            "args_summary": "ls -la",
            "result_summary": "ok",
            "session_id": "sess-1",
            "user_id": "user-1",
        },
    )
    ev = Event(type=EventTypes.SPAN_COMPLETED, data=sp, correlation_id="c1")
    me = translate(ev)
    assert me is not None
    assert me.event_type == EventTypes.ACTION_EXECUTED
    assert me.source_item_id == "shell"
    assert me.session_id == "sess-1"
    assert me.user_id == "user-1"
    assert me.metadata_json["duration_ms"] == 150
    assert me.metadata_json["input"] == "ls -la"


def test_span_completed_other_node_types_skip():
    from magi.events.domain_payloads import SpanCompleted
    for node_type in ("span", "llm_call", "intent_resolution", "turn", "task_lifecycle"):
        sp = SpanCompleted(
            span_id="s", trace_id="t", parent_span_id=None,
            node_type=node_type, name="x", status="ok",
            started_at_ms=0, ended_at_ms=0, duration_ms=0,
            error=None, result_preview=None, turn_id=None,
        )
        ev = Event(type=EventTypes.SPAN_COMPLETED, data=sp)
        assert translate(ev) is None
