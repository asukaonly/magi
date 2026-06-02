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


# === Phase H+2 (this change): origin_channel auto-append =====================
# When a run was triggered by an external channel (e.g. user wrote to us on
# WeChat / Telegram), the reply MUST go back to that channel even if the
# user hasn't explicitly listed it in ``delivery_channels``. Otherwise the
# default ``chat_sse``-only fallback strands the reply in the Magi UI and
# the WeChat user never hears back. ``origin_channel`` is what
# ``RunTrigger.source_channel`` carries from inbound. The resolver appends
# it to the target list unless it's already there.


def test_origin_channel_weixin_appends_to_default_targets():
    """No user_prefs → default chat_sse + origin weixin → both targets."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={}, origin_channel="weixin",
    )
    types = [t.channel_type for t in targets]
    assert types == ["chat_sse", "weixin"]
    for t in targets:
        assert t.magi_session_id == "s1"
        assert t.magi_user_id == "u1"
        assert t.external_chat_id == ""


def test_origin_channel_telegram_appends_to_user_prefs():
    """user_prefs has chat_sse only; origin is telegram → both targets."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["chat_sse"]},
        origin_channel="telegram",
    )
    types = [t.channel_type for t in targets]
    assert types == ["chat_sse", "telegram"]


def test_origin_channel_chat_sse_does_not_duplicate_default():
    """origin=chat_sse is already the default — no duplicate target."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={}, origin_channel="chat_sse",
    )
    types = [t.channel_type for t in targets]
    assert types == ["chat_sse"]


def test_origin_channel_already_in_user_prefs_does_not_duplicate():
    """user_prefs already lists weixin; origin=weixin → no second target."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={"delivery_channels": ["chat_sse", "weixin"]},
        origin_channel="weixin",
    )
    types = [t.channel_type for t in targets]
    assert types == ["chat_sse", "weixin"]


def test_origin_channel_none_preserves_legacy_behavior():
    """origin_channel=None must behave exactly like the pre-change resolver."""
    targets = resolve_delivery_targets(
        user_id="u1", session_id="s1",
        user_prefs={}, origin_channel=None,
    )
    assert len(targets) == 1
    assert targets[0].channel_type == "chat_sse"


def test_origin_channel_blank_or_whitespace_ignored():
    """Defensive: blank / whitespace-only origin_channel is treated as absent."""
    for blank in ("", "   ", "\t"):
        targets = resolve_delivery_targets(
            user_id="u1", session_id="s1",
            user_prefs={}, origin_channel=blank,
        )
        assert len(targets) == 1
        assert targets[0].channel_type == "chat_sse"
