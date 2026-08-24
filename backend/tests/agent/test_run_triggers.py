"""Trigger seam tests (ADR-0004 P3): RunTrigger factory + RunRequest carrier."""
from __future__ import annotations

from magi_plugin_sdk.run_trigger import RunRequest

from magi.agent.run_triggers import build_user_message_trigger, is_external_source


def test_native_source_builds_user_message_trigger() -> None:
    t = build_user_message_trigger(source="api", requester="u1", content="hi", turn_id="t1")
    assert t.trigger_type == "user_message"
    assert t.source_channel == "chat_sse"
    assert t.requester == "u1"
    assert t.correlation == ["t1"]
    assert t.payload == {"content": "hi"}


def test_chat_sse_source_is_native_with_empty_payload() -> None:
    t = build_user_message_trigger(source="chat_sse", requester="u1", content=None, turn_id=None)
    assert t.trigger_type == "user_message"
    assert t.payload == {}
    assert t.correlation == []


def test_external_source_builds_external_inbound_lowercased() -> None:
    t = build_user_message_trigger(source="Telegram", requester="u2", content="yo", turn_id="t2")
    assert t.trigger_type == "external_inbound"
    assert t.source_channel == "telegram"
    assert t.requester == "u2"
    assert t.correlation == ["t2"]


def test_is_external_source_classification() -> None:
    assert is_external_source("telegram") is True
    assert is_external_source("weixin") is True
    assert is_external_source("api") is False
    assert is_external_source("magi-chat") is False
    assert is_external_source("chat_sse") is False
    assert is_external_source(None) is False
    assert is_external_source("") is False
    assert is_external_source("   ") is False  # whitespace → native default


def test_run_request_carries_trigger_and_roundtrips() -> None:
    t = build_user_message_trigger(source="api", requester="u1", content="hi", turn_id="t1")
    req = RunRequest(
        trigger=t, input={"content": "hi"}, session_id="s1", bounds={"max_iterations": 5}
    )
    assert req.trigger is t
    assert req.session_id == "s1"
    assert req.bounds["max_iterations"] == 5

    restored = RunRequest.from_dict(req.to_dict())
    assert restored.trigger.trigger_type == "user_message"
    assert restored.trigger.source_channel == "chat_sse"
    assert restored.session_id == "s1"
    assert restored.input == {"content": "hi"}
    assert restored.bounds == {"max_iterations": 5}


def test_run_request_defaults() -> None:
    t = build_user_message_trigger(source="api", requester="u1", content=None, turn_id=None)
    req = RunRequest(trigger=t)
    assert req.input == {}
    assert req.session_id is None
    assert req.bounds == {}
