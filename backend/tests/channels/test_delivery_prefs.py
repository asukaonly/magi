"""DeliveryPrefs tests — read user's configured delivery channels."""
from __future__ import annotations

from magi.channels.delivery_prefs import resolve_delivery_targets
from magi_plugin_sdk.channels import ChannelTarget


def test_default_returns_chat_sse_target_with_magi_session_id():
    targets = resolve_delivery_targets(user_id="u1", session_id="s1", user_prefs={})
    assert len(targets) == 1
    t = targets[0]
    assert t.channel_type == "chat_sse"
    assert t.magi_session_id == "s1"
    assert t.magi_user_id == "u1"
    assert t.external_chat_id == ""


def test_chat_sse_pref_returns_scheme_only_target():
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["chat_sse"]},
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse"
    assert ":" not in targets[0].channel_type
    assert targets[0].magi_session_id == "s1"


def test_multi_channel_prefs_all_scheme_only():
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["chat_sse", "telegram"]},
    )
    types = [t.channel_type for t in targets]
    assert types == ["chat_sse", "telegram"]
    for t in targets:
        assert ":" not in t.channel_type
        assert t.magi_session_id == "s1"
        assert t.magi_user_id == "u1"
        # No external_chat_id from this layer — channel resolves its own.
        assert t.external_chat_id == ""


def test_invalid_pref_entries_filtered():
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["", "  ", None, 42, "chat_sse"]},
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse"


def test_all_invalid_falls_back_to_default():
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["", "  "]},
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse"


def test_resolve_handles_empty_prefs_list_falls_back_to_default() -> None:
    """An empty list means 'use default' — defaults to chat_sse only."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": []},
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse"
    assert targets[0].magi_session_id == "s1"
