from __future__ import annotations

from pathlib import Path
import pytest


def test_api_services_module_does_not_reexport_runtime_globals() -> None:
    from magi.api import services as api_services

    source = Path(api_services.__file__).read_text(encoding="utf-8")
    assert "events.service_access" not in source
    assert "skills.service_access" not in source
    assert "personality.current_state" not in source


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
