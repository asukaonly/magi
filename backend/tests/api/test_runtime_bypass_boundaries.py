from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_personality_config_reads_injected_persona_provider(monkeypatch):
    from unittest.mock import AsyncMock
    from magi.api.routers import personality_config
    from magi.personality.loader import PersonalityConfig

    config = PersonalityConfig(name="Provider-owned persona", description="provider canary")
    resolve = AsyncMock(return_value=config)
    monkeypatch.setattr(personality_config, "resolve_persona_config", resolve)
    response = await personality_config.get_personality("provider-probe")
    assert response.success is True
    assert response.data["name"] == "Provider-owned persona"
    assert response.data["description"] == "provider canary"
    resolve.assert_awaited_once_with("provider-probe")
