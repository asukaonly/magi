"""Source-aware run provenance factory tests."""
from __future__ import annotations

import pytest
from magi_plugin_sdk.run_trigger import RunTrigger

from magi.agent.run_triggers import build_user_message_trigger


@pytest.mark.parametrize(
    "source,kind,channel",
    [
        (None, "user_message", "chat_sse"),
        ("", "user_message", "chat_sse"),
        ("  ", "user_message", "chat_sse"),
        ("api", "user_message", "chat_sse"),
        ("magi-chat", "user_message", "chat_sse"),
        ("chat_sse", "user_message", "chat_sse"),
        (" Telegram ", "external_inbound", "telegram"),
        ("weixin", "external_inbound", "weixin"),
    ],
)
@pytest.mark.parametrize(
    "content,turn_id,payload,correlation",
    [
        (None, None, {}, []),
        ("hi", "t1", {"content": "hi"}, ["t1"]),
    ],
)
def test_trigger_factory_preserves_origin_and_optional_payload(
    source, kind, channel, content, turn_id, payload, correlation
):
    trigger = build_user_message_trigger(
        source=source, requester="u1", content=content, turn_id=turn_id
    )
    assert trigger == RunTrigger(
        trigger_type=kind,
        source_channel=channel,
        requester="u1",
        priority="foreground",
        correlation=correlation,
        payload=payload,
    )
