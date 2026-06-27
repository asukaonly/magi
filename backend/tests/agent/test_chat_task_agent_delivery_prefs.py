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


@pytest.mark.asyncio
async def test_user_prefs_provider_returns_empty_dict_when_no_preference(monkeypatch):
    """When delivery_channels is unset / falsy, return empty dict so the
    downstream resolver safely defaults to chat_sse-only delivery."""
    import magi.channels.chat_delivery_dispatcher as delivery_mod

    monkeypatch.setattr(
        delivery_mod, "get_user_preference", lambda k, default=None: default
    )

    prefs = await read_configured_delivery_prefs("u-test")
    assert prefs == {}


@pytest.mark.asyncio
async def test_user_prefs_provider_ignores_non_list_value(monkeypatch):
    """Defensive: when the stored preference is not a list (e.g. legacy string),
    treat it as unset and return empty so resolution falls back to default."""
    import magi.channels.chat_delivery_dispatcher as delivery_mod

    monkeypatch.setattr(
        delivery_mod,
        "get_user_preference",
        lambda k, default=None: "telegram" if k == "delivery_channels" else default,
    )

    prefs = await read_configured_delivery_prefs("u-test")
    assert prefs == {}


@pytest.mark.asyncio
async def test_user_prefs_provider_empty_list_returns_empty_dict(monkeypatch):
    """An empty list should be treated as 'no preference set' — return {}
    rather than {'delivery_channels': []} which would suppress all delivery."""
    import magi.channels.chat_delivery_dispatcher as delivery_mod

    monkeypatch.setattr(
        delivery_mod,
        "get_user_preference",
        lambda k, default=None: [] if k == "delivery_channels" else default,
    )

    prefs = await read_configured_delivery_prefs("u-test")
    assert prefs == {}
