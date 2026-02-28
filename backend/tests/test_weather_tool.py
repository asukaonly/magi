"""
Tests for weather tool provider-error guidance.
"""
from types import MethodType

import pytest

from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.schema import ToolExecutionContext, ToolResult


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_qweather_invalid_host_returns_system_settings_guidance():
    tool = WeatherTool()
    tool.get_available_providers = MethodType(lambda self: ["qweather"], tool)

    async def fake_execute_with_provider(self, provider_name, params):
        return ToolResult(
            success=False,
            error="QWeather requires a configured base URL. Please get it from https://console.qweather.com/setting.",
            error_code="PROVIDER_ERROR",
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"location": "Hangzhou"}, _context())

    assert result.success is False
    assert result.error_code == "QWEATHER_BASE_URL_REQUIRED"
    assert result.data["config_tool"] == "system-settings"
    assert result.data["config_path"] == "tool.weather.providers.qweather.base_url"
    assert result.data["reference_url"] == "https://console.qweather.com/setting"


@pytest.mark.asyncio
async def test_qweather_other_provider_error_passthrough():
    tool = WeatherTool()
    tool.get_available_providers = MethodType(lambda self: ["qweather"], tool)

    async def fake_execute_with_provider(self, provider_name, params):
        return ToolResult(
            success=False,
            error="GeoAPI API error: 500 | body=internal error",
            error_code="PROVIDER_ERROR",
        )

    tool.execute_with_provider = MethodType(fake_execute_with_provider, tool)

    result = await tool.execute({"location": "Hangzhou"}, _context())

    assert result.success is False
    assert result.error_code == "PROVIDER_ERROR"
    assert result.error == "GeoAPI API error: 500 | body=internal error"
