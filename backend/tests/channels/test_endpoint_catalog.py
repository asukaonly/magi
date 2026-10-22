"""Endpoint discovery preserves account and thread identity."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from magi_plugin_sdk.audio import AudioOutputTarget, AudioTargetInfo

from magi.channels.endpoints import EndpointCatalog


def catalog():
    mapper = SimpleNamespace(list_all=AsyncMock(return_value=[SimpleNamespace(
        channel_type="account:telegram", external_chat_id="group", external_thread_id=thread,
        metadata_json='{"display_name":"Family"}',
    ) for thread in ("one", "two")]))
    audio = SimpleNamespace(channel_type="house:speaker", list_targets=AsyncMock(return_value=(
        AudioTargetInfo(AudioOutputTarget("house:speaker", "living"), "Living room", True),
    )))
    registry = SimpleNamespace(get=Mock(return_value=None), all_audio_channels=lambda: [audio])
    return EndpointCatalog(registry, mapper)


@pytest.mark.asyncio
async def test_catalog_keeps_threads_and_audio_capabilities_separate():
    entries = await catalog().list_endpoints()
    assert len(entries) == 3
    assert [item["endpoint"]["thread_id"] for item in entries[:2]] == ["one", "two"]
    assert all(item["endpoint"]["connection_id"] == "account" for item in entries[:2])
    assert all(not item["available"] for item in entries[:2])
    assert entries[-1]["capabilities"] == ["audio"]


@pytest.mark.asyncio
async def test_preferences_accept_audio_and_reject_unknown_destinations(monkeypatch):
    owner = catalog()
    entries = await owner.list_endpoints()
    save = Mock(return_value=True)
    monkeypatch.setattr("magi.channels.endpoints.save_config", save)
    with pytest.raises(ValueError, match="known output"):
        await owner.set_delivery_preferences([{**entries[0]["endpoint"], "target_id": "stranger"}])
    save.assert_not_called()
    targets = [entry["endpoint"] for entry in entries]
    await owner.set_delivery_preferences(targets)
    save.assert_called_once_with({"preferences.delivery_targets": targets})


@pytest.mark.asyncio
async def test_discovery_failure_does_not_hide_known_conversations():
    owner = catalog()
    owner._registry.all_audio_channels()[0].list_targets.side_effect = TimeoutError
    assert len(await owner.list_endpoints()) == 2
