"""Tests for tool enabled flags enforced at execution time."""

import pytest

import magi.config as config_module
from magi.config.models import AppConfig
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolErrorCode, ToolExecutionContext


def test_registry_list_tools_hides_disabled_builtin_tool(monkeypatch):
    config = AppConfig()
    config.tools.weather.enabled = False
    monkeypatch.setattr(config_module, "get_config", lambda: config)

    registry = ToolRegistry()
    registry.register(WeatherTool)

    assert "weather" not in registry.list_tools()
    assert registry.get_all_tools_info() == []


@pytest.mark.asyncio
async def test_registry_blocks_disabled_builtin_tool(monkeypatch):
    config = AppConfig()
    config.tools.weather.enabled = False
    monkeypatch.setattr(config_module, "get_config", lambda: config)

    registry = ToolRegistry()
    registry.register(WeatherTool)

    result = await registry.execute(
        "weather",
        {"location": "Tokyo"},
        ToolExecutionContext(agent_id="test-agent"),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.POLICY_BLOCKED.value
    assert "disabled" in str(result.error).lower()
