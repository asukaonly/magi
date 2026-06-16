"""Tests for weather tool provider behavior."""

from types import SimpleNamespace

import pytest

import magi.config as config_module
import magi.tools.builtin.weather_tool as weather_tool_module
from magi.config.models import AppConfig
from magi.i18n import language_context
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.providers.weather.open_meteo import OpenMeteoProvider
from magi.tools.schema import ToolExecutionContext


def test_weather_tool_defaults_to_keyless_open_meteo(monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(config_module, "get_config", lambda: config)
    monkeypatch.setattr(weather_tool_module, "get_config", lambda: config)

    tool = WeatherTool()

    assert config.tools.weather.default_provider == "openmeteo"
    assert tool.get_all_provider_names() == ["openmeteo", "qweather"]
    assert tool.get_available_providers() == ["openmeteo"]


@pytest.mark.asyncio
async def test_open_meteo_current_weather_uses_geocoding_and_forecast(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        def __init__(self, payload: dict):
            self.status = 200
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def json(self):
            return self._payload

        async def text(self):
            return ""

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def get(self, url, *, params=None, proxy=None):
            calls.append((url, dict(params or {})))
            if "geocoding-api.open-meteo.com" in url:
                return FakeResponse(
                    {
                        "results": [
                            {
                                "name": "Tokyo",
                                "latitude": 35.6764,
                                "longitude": 139.65,
                                "country": "Japan",
                                "admin1": "Tokyo",
                            }
                        ]
                    }
                )
            return FakeResponse(
                {
                    "current": {
                        "time": "2026-06-14T06:00",
                        "temperature_2m": 26.5,
                        "apparent_temperature": 28.1,
                        "relative_humidity_2m": 61,
                        "precipitation": 0.0,
                        "weather_code": 2,
                        "wind_speed_10m": 9.2,
                        "wind_direction_10m": 180,
                    }
                }
            )

    monkeypatch.setattr(
        "magi.tools.providers.weather.open_meteo.aiohttp.ClientSession",
        FakeSession,
    )

    result = await OpenMeteoProvider().execute(
        {"location": "Tokyo", "lang": "en", "mode": "current"},
        SimpleNamespace(api_key=None, base_url=None),
    )

    assert result["provider"] == "openmeteo"
    assert result["location"]["name"] == "Tokyo"
    assert result["weather"]["temperature"] == 26.5
    assert result["weather"]["condition"] == "Partly cloudy"
    assert calls[0][1]["name"] == "Tokyo"
    assert calls[1][1]["latitude"] == "35.6764"


@pytest.mark.asyncio
async def test_weather_tool_uses_open_meteo_by_default(monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(weather_tool_module, "get_config", lambda: config)

    captured = {}
    tool = WeatherTool()

    async def fake_execute_with_provider(provider_name, params):
        captured["provider_name"] = provider_name
        captured["params"] = params
        return weather_tool_module.ToolResult(
            success=True,
            data={"provider": provider_name},
        )

    monkeypatch.setattr(tool, "execute_with_provider", fake_execute_with_provider)

    result = await tool.execute(
        {"location": "Tokyo"},
        ToolExecutionContext(agent_id="test-agent"),
    )

    assert result.success is True
    assert captured["provider_name"] == "openmeteo"
    assert captured["params"]["lang"] == "en"


@pytest.mark.asyncio
async def test_weather_tool_uses_current_language_when_lang_is_omitted(monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(weather_tool_module, "get_config", lambda: config)

    captured = {}
    tool = WeatherTool()

    async def fake_execute_with_provider(provider_name, params):
        captured["provider_name"] = provider_name
        captured["params"] = params
        return weather_tool_module.ToolResult(
            success=True,
            data={"provider": provider_name},
        )

    monkeypatch.setattr(tool, "execute_with_provider", fake_execute_with_provider)

    with language_context("zh-CN"):
        result = await tool.execute(
            {"location": "北京"},
            ToolExecutionContext(agent_id="test-agent"),
        )

    assert result.success is True
    assert captured["provider_name"] == "openmeteo"
    assert captured["params"]["lang"] == "zh"
