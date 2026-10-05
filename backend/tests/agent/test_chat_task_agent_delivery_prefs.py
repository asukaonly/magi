"""Channel delivery prefs provider reads delivery_channels from config."""

from __future__ import annotations

import pytest

from magi.channels.chat_delivery_dispatcher import read_configured_delivery_prefs


@pytest.mark.asyncio
async def test_user_prefs_provider_reads_delivery_channels_from_config(monkeypatch):
    """Provider returns the {"delivery_channels": [...]} shape expected by
    ``resolve_delivery_targets`` when the config has a non-empty list."""
    captured_keys: list[str] = []

    def fake_get_user_preference(key, default=None):
        captured_keys.append(key)
        if key == "delivery_channels":
            return ["chat_sse", "telegram"]
        return default

    import magi.channels.chat_delivery_dispatcher as delivery_mod

    monkeypatch.setattr(delivery_mod, "get_user_preference", fake_get_user_preference)

    prefs = await read_configured_delivery_prefs("u-test")
    assert prefs == {"delivery_channels": ["chat_sse", "telegram"]}
    assert "delivery_channels" in captured_keys


@pytest.mark.parametrize("stored", [None, "telegram", [], {}])
@pytest.mark.asyncio
async def test_unset_delivery_preferences_fall_back_without_dropping_external_origin(
    monkeypatch, stored
):
    from magi.channels.delivery_prefs import resolve_delivery_targets
    from magi_plugin_sdk.channels import ChannelTarget
    import magi.channels.chat_delivery_dispatcher as delivery_mod

    monkeypatch.setattr(
        delivery_mod,
        "get_user_preference",
        lambda key, default=None: stored if key == "delivery_channels" else default,
    )
    prefs = await read_configured_delivery_prefs("u-test")
    assert prefs == {}
    assert resolve_delivery_targets(
        user_id="u-test", session_id="s1", user_prefs=prefs, origin_channel="telegram"
    ) == [
        ChannelTarget(
            channel_type="chat_sse",
            external_chat_id="",
            magi_user_id="u-test",
            magi_session_id="s1",
        ),
        ChannelTarget(
            channel_type="telegram",
            external_chat_id="",
            magi_user_id="u-test",
            magi_session_id="s1",
        ),
    ]
