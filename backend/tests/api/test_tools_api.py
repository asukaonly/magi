"""Tests for tool router route matching."""

import pytest
from fastapi import HTTPException
from starlette.routing import Match

import magi.config as config_module
from magi.api.routers.tools import (
    ToolConfigUpdateRequest,
    _build_tool_config_response,
    _get_tool_display_name,
    list_tools_with_config,
    tools_router,
    update_tool_config,
)
from magi.config.models import AppConfig
from magi.i18n import language_context
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.weather.open_meteo import OpenMeteoProvider
from magi.tools.providers.weather.qweather import QWeatherProvider


def test_tools_config_route_matches_static_endpoint_first():
    scope = {
        "type": "http",
        "path": "/config",
        "method": "GET",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    for route in tools_router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            assert route.endpoint is list_tools_with_config
            return

    pytest.fail("Expected /config to match the static tool config endpoint")


def test_powershell_display_name_preserves_product_casing() -> None:
    assert _get_tool_display_name("powershell") == "PowerShell"


def test_web_fetch_config_response_has_no_user_provider_toggle():
    response = _build_tool_config_response("web-fetch", WebFetchTool())

    assert response.enabled is True
    assert response.config_specs == []
    assert response.current_values == {}


def test_web_search_config_response_exposes_provider_enum_and_targeted_specs():
    response = _build_tool_config_response("web-search", WebSearchTool())

    default_provider_spec = next(spec for spec in response.config_specs if spec.path == "default_provider")
    api_key_spec = next(spec for spec in response.config_specs if spec.path == "providers.{provider}.api_key")
    base_url_spec = next(spec for spec in response.config_specs if spec.path == "providers.{provider}.base_url")

    assert default_provider_spec.enum == ["duckduckgo", "brave", "perplexity", "searxng", "tavily"]
    assert api_key_spec.providers == ["brave", "perplexity", "tavily"]
    assert base_url_spec.providers == ["duckduckgo", "searxng"]


def test_web_search_provider_parameter_is_not_exposed_to_llm():
    schema = WebSearchTool().get_schema()

    assert "provider" not in {param.name for param in schema.parameters}
    assert "configured default provider" in schema.description


def test_web_search_schema_disables_tool_retry_for_terminal_provider_errors():
    schema = WebSearchTool().get_schema()

    assert schema.retry_on_failure is False
    assert schema.max_retries == 0


def test_web_search_config_response_omits_sensitive_current_values(monkeypatch):
    config = AppConfig()
    config.tools.web_search.providers["brave"].api_key = "secret-key"

    monkeypatch.setattr(config_module, "get_config", lambda: config)

    response = _build_tool_config_response("web-search", WebSearchTool())

    assert "providers.brave.api_key" not in response.current_values


def test_weather_tool_requires_only_api_key_for_qweather():
    tool_response = _build_tool_config_response("weather", WeatherTool())
    openmeteo_info = next(provider for provider in tool_response.providers if provider.name == "openmeteo")
    qweather_info = next(provider for provider in tool_response.providers if provider.name == "qweather")
    openmeteo_provider = OpenMeteoProvider()
    qweather_provider = QWeatherProvider()

    assert openmeteo_info.required_config == []
    assert openmeteo_provider.is_ready(ProviderConfig()) is True
    assert qweather_info.required_config == ["providers.qweather.api_key"]
    assert qweather_provider.is_ready(ProviderConfig(api_key="token", base_url="devapi.qweather.com")) is True
    assert qweather_provider.is_ready(ProviderConfig(api_key="token", base_url="")) is True


@pytest.mark.asyncio
async def test_update_tool_config_returns_success_without_logger_crash(monkeypatch):
    monkeypatch.setattr(config_module, "save_config", lambda updates: True)
    monkeypatch.setattr(config_module, "reload_config", lambda: None)

    with language_context("en"):
        response = await update_tool_config(
            "web-search",
            ToolConfigUpdateRequest(updates={"default_provider": "duckduckgo"}),
        )

    assert response["success"] is True
    assert response["message"] == "Tool web-search configuration updated"
    assert response["updated_keys"] == ["default_provider"]


@pytest.mark.asyncio
async def test_update_tool_config_returns_localized_no_updates() -> None:
    with language_context("zh-CN"):
        response = await update_tool_config(
            "web-search",
            ToolConfigUpdateRequest(updates={}),
        )

    assert response == {"success": True, "message": "没有需要应用的更新"}


@pytest.mark.asyncio
async def test_update_tool_config_returns_localized_not_found() -> None:
    with language_context("zh-CN"):
        with pytest.raises(HTTPException) as exc_info:
            await update_tool_config(
                "missing-tool",
                ToolConfigUpdateRequest(updates={"enabled": True}),
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "未找到工具：missing-tool"
