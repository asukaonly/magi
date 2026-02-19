"""
Tests for the refactored system-settings routing behavior.
"""
from types import MethodType, SimpleNamespace

import pytest

from magi.tools.builtin.system_settings_tool import SystemSettingsTool
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.registry import tool_registry
from magi.tools.schema import ToolExecutionContext, ToolResult


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_list_contains_app_and_tool_paths():
    tool = SystemSettingsTool()
    result = await tool.execute({"action": "list"}, _context())

    assert result.success is True
    assert "app.llm.model" in result.data["available_paths"]
    assert "tool.web-search.default_provider" in result.data["available_paths"]
    assert "tool.web-fetch.default_provider" in result.data["available_paths"]
    assert "tool.weather.providers.{provider}.api_key" in result.data["available_paths"]


@pytest.mark.asyncio
async def test_set_app_path_uses_save_config_with_type_conversion(monkeypatch):
    tool = SystemSettingsTool()
    captured = {}

    fake_config = SimpleNamespace(
        llm=SimpleNamespace(timeout=60),
    )

    def fake_get_config():
        return fake_config

    def fake_save_config(updates):
        captured.update(updates)
        return True

    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.get_config", fake_get_config)
    monkeypatch.setattr("magi.tools.builtin.system_settings_tool.save_config", fake_save_config)

    result = await tool.execute(
        {"action": "set", "path": "app.llm.timeout", "value": "120"},
        _context(),
    )

    assert result.success is True
    assert captured == {"llm.timeout": 120}


@pytest.mark.asyncio
async def test_set_tool_path_routes_to_tool_update(monkeypatch):
    tool = SystemSettingsTool()
    web_tool = tool_registry.get_tool("web-search")
    assert web_tool is not None

    called = {}

    async def fake_update_config(self, path, value, context):
        called["path"] = path
        called["value"] = value
        return ToolResult(success=True, data={"ok": True})

    monkeypatch.setattr(web_tool, "update_config", MethodType(fake_update_config, web_tool))

    result = await tool.execute(
        {
            "action": "set",
            "path": "tool.web-search.providers.brave.api_key",
            "value": "test-key",
        },
        _context(),
    )

    assert result.success is True
    assert called["path"] == "providers.brave.api_key"
    assert called["value"] == "test-key"


@pytest.mark.asyncio
async def test_set_web_fetch_tool_path_routes_to_tool_update(monkeypatch):
    tool = SystemSettingsTool()
    web_fetch_tool = tool_registry.get_tool("web-fetch")
    assert web_fetch_tool is not None

    called = {}

    async def fake_update_config(self, path, value, context):
        called["path"] = path
        called["value"] = value
        return ToolResult(success=True, data={"ok": True})

    monkeypatch.setattr(web_fetch_tool, "update_config", MethodType(fake_update_config, web_fetch_tool))

    result = await tool.execute(
        {
            "action": "set",
            "path": "tool.web-fetch.default_provider",
            "value": "browser",
        },
        _context(),
    )

    assert result.success is True
    assert called["path"] == "default_provider"
    assert called["value"] == "browser"


@pytest.mark.asyncio
async def test_get_sensitive_path_denied():
    tool = SystemSettingsTool()
    result = await tool.execute(
        {"action": "get", "path": "tool.web-search.providers.brave.api_key"},
        _context(),
    )

    assert result.success is False
    assert result.error_code == "ACCESS_DENIED"


def test_weather_and_web_search_schema_remove_config_action():
    weather_param_names = {item.name for item in WeatherTool().get_schema().parameters}
    web_search_param_names = {item.name for item in WebSearchTool().get_schema().parameters}
    web_fetch_param_names = {item.name for item in WebFetchTool().get_schema().parameters}

    assert "action" not in weather_param_names
    assert "config_action" not in weather_param_names
    assert "api_key" not in weather_param_names

    assert "action" not in web_search_param_names
    assert "config_action" not in web_search_param_names
    assert "api_key" not in web_search_param_names

    assert "action" not in web_fetch_param_names
    assert "config_action" not in web_fetch_param_names
    assert "api_key" not in web_fetch_param_names
