"""DeliveryPrefs tests — read user's configured delivery channels."""
from __future__ import annotations

from magi.channels.delivery_prefs import resolve_delivery_targets
from magi_plugin_sdk.channels import ChannelTarget


def test_resolve_returns_chat_sse_only_by_default() -> None:
    """When user has no preference set, default is chat_sse for the
    current session only."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1", user_prefs={},
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse:s1"


def test_resolve_includes_external_channels_when_user_preferred() -> None:
    """A user with telegram pref configured gets BOTH chat_sse + telegram."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={
            "delivery_channels": ["chat_sse", "telegram:U42"],
        },
    )
    assert len(targets) == 2
    channel_ids = {t.channel_type for t in targets}
    assert "chat_sse:s1" in channel_ids
    assert "telegram:U42" in channel_ids


def test_resolve_chat_sse_is_replaced_with_session_specific_id() -> None:
    """User prefs say 'chat_sse' (generic); resolver expands to 'chat_sse:<session>'."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="my_session",
        user_prefs={"delivery_channels": ["chat_sse"]},
    )
    assert targets[0].channel_type == "chat_sse:my_session"


def test_resolve_handles_empty_prefs_list_falls_back_to_default() -> None:
    """An empty list means 'use default' — defaults to chat_sse only."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": []},
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse:s1"


def test_resolve_filters_unknown_channel_ids() -> None:
    """Unknown / malformed channel IDs are silently dropped to keep delivery robust."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["chat_sse", ""]},
    )
    assert len(targets) == 1
