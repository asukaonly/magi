from __future__ import annotations

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import (
    ToolInvocationCompleted,
    TaskContext,
    ToolError,
    UserMessageReceived,
    AssistantResponseProduced,
    SourceEventEmitted,
)
from magi.memory.event_translation import translate
from magi.memory.evidence import classify_event_evidence, resolve_l2_policy
from magi.memory.event_contracts import MemoryDomain


def test_tool_invocation_completed_to_action_executed():
    payload = ToolInvocationCompleted(
        tool_name="shell",
        tool_category="external_tool",
        success=True,
        duration_ms=12.5,
        started_at=1.0,
        finished_at=2.0,
        args_summary="ls -la",
        result_summary="ok",
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
        tool_name="shell",
        tool_category="external_tool",
        success=False,
        duration_ms=1.0,
        started_at=1.0,
        finished_at=2.0,
        args_summary="x",
        result_summary=None,
        error=err,
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


def test_recall_feedback_stays_conversational_and_cannot_feed_cognition():
    payload = UserMessageReceived(
        content="That record is irrelevant here.",
        context=TaskContext("s", "t", None, "u"),
        interaction_kind="recall_feedback",
        metadata={"author_type": "user"},
    )

    me = translate(Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload))

    assert me is not None
    assert me.event_type == EventTypes.USER_MESSAGE
    assert me.memory_domain == MemoryDomain.INTERACTION
    assert me.cognition_eligible is False
    assert me.metadata_json == {"interaction_kind": "recall_feedback"}
    classification = classify_event_evidence(me)
    policy = resolve_l2_policy(classification)
    assert classification.evidence_class == "user_request"
    assert classification.reason_code == "user_recall_feedback_interaction"
    assert policy.l1_retrieval_scope == "conversation_only"
    assert policy.allow_graph_write is False
    assert policy.allow_assertion_write is False


def test_first_context_metadata_and_l2_priority_hints_survive_translation():
    first_context = {
        "question_id": "recent_feeling",
        "question_text": "最近有哪件小事，让你心情有一点变化？",
    }
    payload = UserMessageReceived(
        content="我最近失恋了，你能陪我聊聊吗？",
        context=TaskContext("s", "t", None, "u"),
        interaction_kind="first_context_story",
        metadata={
            "first_context": first_context,
            "l2_batch_owner": "bootstrap:u:test",
            "l2_batch_max_events": 1,
            "l2_batch_max_estimated_tokens": 128,
            "l2_batch_min_ready_events": 1,
            "l2_batch_max_wait_seconds": 1.0,
            "untrusted": "drop-me",
        },
    )

    memory_event = translate(
        Event(type=EventTypes.USER_MESSAGE_RECEIVED, data=payload, source="chat")
    )

    assert memory_event is not None
    assert memory_event.metadata_json == {
        "interaction_kind": "first_context_story",
        "first_context": first_context,
        "l2_batch_owner": "bootstrap:u:test",
        "l2_batch_max_events": 1,
        "l2_batch_max_estimated_tokens": 128,
        "l2_batch_min_ready_events": 1,
        "l2_batch_max_wait_seconds": 1.0,
    }
    classification = classify_event_evidence(memory_event)
    policy = resolve_l2_policy(classification)
    assert classification.evidence_class == "user_self_report"
    assert classification.reason_code == "first_context_story_with_self_report"
    assert policy.allow_graph_write is True
    assert policy.allow_assertion_write is True


def test_assistant_response_produced_translation():
    payload = AssistantResponseProduced(
        content="reply",
        context=TaskContext("s", "t", None, "u"),
    )
    me = translate(Event(type=EventTypes.ASSISTANT_RESPONSE_PRODUCED, data=payload))
    assert me is not None
    assert me.event_type == EventTypes.AI_RESPONSE
    assert me.content == "reply"


def test_source_event_emitted_translation():
    """C producer (with policy_dict) is the only supported source shape."""
    from magi_plugin_sdk.sources import SourceMemoryPolicy

    payload = SourceEventEmitted(
        source_name="screen_time",
        payload={"app": "chrome", "duration": 60},
        context=TaskContext(None, None, None, "u"),
        source_id="screen_time",
        policy_dict=SourceMemoryPolicy().to_dict(),
    )
    me = translate(Event(type=EventTypes.SOURCE_EVENT_EMITTED, data=payload))
    assert me is not None
    assert me.event_type == "SOURCE_EVENT"


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
        span_id="s1",
        trace_id="t1",
        parent_span_id=None,
        node_type="tool_invocation",
        name="shell",
        status="ok",
        started_at_ms=1000,
        ended_at_ms=1150,
        duration_ms=150,
        error=None,
        result_preview="ok",
        turn_id="turn-1",
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

    for node_type in ("span", "llm_call", "capability_resolution", "turn"):
        sp = SpanCompleted(
            span_id="s",
            trace_id="t",
            parent_span_id=None,
            node_type=node_type,
            name="x",
            status="ok",
            started_at_ms=0,
            ended_at_ms=0,
            duration_ms=0,
            error=None,
            result_preview=None,
            turn_id=None,
        )
        ev = Event(type=EventTypes.SPAN_COMPLETED, data=sp)
        assert translate(ev) is None


def test_span_completed_task_lifecycle_ok_translates_to_task_completed():
    from magi.events.domain_payloads import SpanCompleted

    sp = SpanCompleted(
        span_id="s1",
        trace_id="t1",
        parent_span_id=None,
        node_type="task_lifecycle",
        name="chat",
        status="ok",
        started_at_ms=1000,
        ended_at_ms=2000,
        duration_ms=1000,
        error=None,
        result_preview="done",
        turn_id="turn-1",
        attributes={
            "task_id": "orch-1",
            "task_type": "chat",
            "summary": "done",
            "user_id": "u",
            "session_id": "s",
            "started_at": 1.0,
            "finished_at": 2.0,
        },
    )
    ev = Event(type=EventTypes.SPAN_COMPLETED, data=sp, correlation_id="c1")
    me = translate(ev)
    assert me is not None
    assert me.event_type == EventTypes.TASK_COMPLETED


def test_span_completed_task_lifecycle_error_translates_to_task_failed():
    from magi.events.domain_payloads import SpanCompleted, ToolError

    sp = SpanCompleted(
        span_id="s1",
        trace_id="t1",
        parent_span_id=None,
        node_type="task_lifecycle",
        name="chat",
        status="error",
        started_at_ms=1000,
        ended_at_ms=2000,
        duration_ms=1000,
        error=ToolError(type="LaunchError", message="boom"),
        result_preview=None,
        turn_id="turn-1",
        attributes={
            "task_id": "orch-2",
            "task_type": "chat",
            "user_id": "u",
            "session_id": "s",
        },
    )
    ev = Event(type=EventTypes.SPAN_COMPLETED, data=sp)
    me = translate(ev)
    assert me is not None
    assert me.event_type == EventTypes.TASK_FAILED


def test_source_main_path_uses_build_source_memory_event():
    """C producer (with policy_dict) goes through build_source_memory_event."""
    from magi_plugin_sdk.sources import SourceMemoryPolicy

    payload = SourceEventEmitted(
        source_name="screen_time",
        payload={},
        context=TaskContext(None, None, None, "user-1"),
        source_id="screen_time",
        output_dict={
            "source_type": "external_activity",
            "source_item_id": "win-app-foo",
            "occurred_at": 1700.0,
            "captured_at": 1700.5,
            "domain_payload": {},
            "raw_payload_ref": None,
            "provenance": {},
            "tags": [],
            "entities": [],
            "content_blocks": [],
        },
        metadata_dict={},
        policy_dict=SourceMemoryPolicy().to_dict(),
        projection_dict={
            "title": "T",
            "summary": "S",
            "content": "C",
            "embedding_head": "H",
            "metadata": {},
        },
        occurred_at=1700.0,
        owner_user_id="user-1",
        idempotency_key="ik-1",
    )
    ev = Event(
        type=EventTypes.SOURCE_EVENT_EMITTED,
        data=payload,
        event_id="evt-X",
        correlation_id="corr-X",
    )
    me = translate(ev)
    assert me is not None
    assert me.event_id == "evt-X"
    assert me.correlation_id == "corr-X"
    assert me.event_type == "SOURCE_EVENT"
    assert me.source == "external_activity"
    assert me.idempotency_key == "ik-1"
    assert me.user_id == "user-1"
