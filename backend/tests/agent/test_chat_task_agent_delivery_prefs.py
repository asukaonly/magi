"""Configured delivery preferences require fully addressed endpoints."""
import pytest
from magi.channels import chat_delivery_dispatcher as delivery
from magi_plugin_sdk.endpoints import EndpointRef


@pytest.mark.asyncio
async def test_reads_explicit_endpoint_preferences(monkeypatch):
    target = EndpointRef("account", "telegram", "chat", "topic").to_dict()
    monkeypatch.setattr(delivery, "get_user_preference", lambda key, default=None: [target] if key == "delivery_targets" else default)
    assert await delivery.read_configured_delivery_prefs("u") == {"delivery_targets": [target]}


@pytest.mark.asyncio
async def test_unconfigured_preferences_have_no_additional_destinations(monkeypatch):
    monkeypatch.setattr(delivery, "get_user_preference", lambda key, default=None: default)
    assert await delivery.read_configured_delivery_prefs("u") == {"delivery_targets": []}


@pytest.mark.asyncio
async def test_scheme_only_configuration_requires_explicit_migration(monkeypatch):
    monkeypatch.setattr(delivery, "get_user_preference", lambda key, default=None: ["telegram"] if key == "delivery_channels" else default)
    with pytest.raises(ValueError, match="explicit delivery targets"):
        await delivery.read_configured_delivery_prefs("u")
