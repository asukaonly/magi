"""DeliveryPrefs tests — read user's configured delivery channels."""

from __future__ import annotations

import pytest

from magi.channels.delivery_prefs import resolve_delivery_targets
from magi_plugin_sdk.channels import ChannelTarget


@pytest.mark.parametrize(
    "prefs,expected",
    [
        ({}, ["chat_sse"]),
        ({"delivery_channels": []}, ["chat_sse"]),
        ({"delivery_channels": "telegram"}, ["chat_sse"]),
        ({"delivery_channels": ["", "  ", None, 42]}, ["chat_sse"]),
        ({"delivery_channels": ["chat_sse"]}, ["chat_sse"]),
        ({"delivery_channels": ["", None, 42, "telegram"]}, ["telegram"]),
        ({"delivery_channels": ["chat_sse", "telegram"]}, ["chat_sse", "telegram"]),
    ],
)
def test_delivery_preferences_resolve_complete_target_identity(prefs, expected):
    targets = resolve_delivery_targets(user_id="u1", session_id="s1", user_prefs=prefs)
    assert targets == [
        ChannelTarget(
            channel_type=name, external_chat_id="", magi_session_id="s1", magi_user_id="u1"
        )
        for name in expected
    ]


@pytest.mark.parametrize(
    "prefs,origin,expected",
    [
        ({}, "weixin", ["chat_sse", "weixin"]),
        ({"delivery_channels": ["chat_sse"]}, "telegram", ["chat_sse", "telegram"]),
        ({"delivery_channels": ["chat_sse", "weixin"]}, "weixin", ["chat_sse", "weixin"]),
        ({}, "chat_sse", ["chat_sse"]),
        ({}, None, ["chat_sse"]),
        ({}, "", ["chat_sse"]),
        ({}, "   ", ["chat_sse"]),
        ({}, "\t", ["chat_sse"]),
    ],
)
def test_origin_channel_is_returned_once_without_losing_session_identity(prefs, origin, expected):
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1", user_prefs=prefs, origin_channel=origin
    )
    assert targets == [
        ChannelTarget(
            channel_type=name, external_chat_id="", magi_session_id="s1", magi_user_id="u1"
        )
        for name in expected
    ]
