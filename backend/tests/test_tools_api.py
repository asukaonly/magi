"""Tests for tool router route matching."""

import pytest
from starlette.routing import Match

import magi.config as config_module
from magi.api.routers.tools import (
    ToolConfigUpdateRequest,
    _build_tool_config_response,
    list_tools_with_config,
    tools_router,
    update_tool_config,
)
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.providers.base import ProviderConfig
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


def test_web_fetch_config_response_uses_default_provider():
    response = _build_tool_config_response("web-fetch", WebFetchTool())

    assert response.enabled is True
    assert response.current_values["default_provider"] == "http"


def test_web_search_config_response_exposes_provider_enum_and_targeted_specs():
    response = _build_tool_config_response("web-search", WebSearchTool())

    default_provider_spec = next(spec for spec in response.config_specs if spec.path == "default_provider")
    api_key_spec = next(spec for spec in response.config_specs if spec.path == "providers.{provider}.api_key")
    base_url_spec = next(spec for spec in response.config_specs if spec.path == "providers.{provider}.base_url")

    assert default_provider_spec.enum == ["duckduckgo", "brave", "perplexity", "tavily"]
    assert api_key_spec.providers == ["brave", "perplexity", "tavily"]
    assert base_url_spec.providers == ["duckduckgo"]


def test_weather_tool_requires_api_key_and_base_url_for_qweather():
    tool_response = _build_tool_config_response("weather", WeatherTool())
    qweather_info = next(provider for provider in tool_response.providers if provider.name == "qweather")
    qweather_provider = QWeatherProvider()

    assert qweather_info.required_config == [
        "providers.qweather.api_key",
        "providers.qweather.base_url",
    ]
    assert qweather_provider.is_ready(ProviderConfig(api_key="token", base_url="devapi.qweather.com")) is True
    assert qweather_provider.is_ready(ProviderConfig(api_key="token", base_url="")) is False


@pytest.mark.asyncio
async def test_update_tool_config_returns_success_without_logger_crash(monkeypatch):
    monkeypatch.setattr(config_module, "save_config", lambda updates: True)
    monkeypatch.setattr(config_module, "reload_config", lambda: None)

    response = await update_tool_config(
        "web-search",
        ToolConfigUpdateRequest(updates={"default_provider": "duckduckgo"}),
    )

    assert response["success"] is True
    assert response["updated_keys"] == ["default_provider"]
