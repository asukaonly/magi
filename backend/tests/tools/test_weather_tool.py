"""Tests for weather tool provider behavior."""

from types import SimpleNamespace

import pytest

import magi.config as config_module
import magi.tools.builtin.weather_tool as weather_tool_module
import magi.tools.providers.weather.qweather as qweather_module
from magi.config.models import AppConfig
from magi.i18n import language_context
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.providers.weather.open_meteo import OpenMeteoProvider
from magi.tools.providers.weather.qweather import QWeatherProvider
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


@pytest.mark.asyncio
async def test_qweather_forecast_maps_daily_items(monkeypatch):
    calls: list[tuple[str, dict, dict | None]] = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def json(self):
            return {
                "code": "200",
                "daily": [
                    {
                        "fxDate": "2026-06-30",
                        "sunrise": "05:00",
                        "sunset": "19:00",
                        "tempMax": "31",
                        "tempMin": "24",
                        "textDay": "Sunny",
                        "textNight": "Cloudy",
                        "iconDay": "100",
                        "iconNight": "104",
                        "windDirDay": "NE",
                        "windScaleDay": "3",
                        "windSpeedDay": "16",
                        "windDirNight": "E",
                        "windScaleNight": "2",
                        "windSpeedNight": "9",
                        "humidity": "65",
                        "precip": "0.0",
                        "pressure": "1005",
                        "vis": "10",
                        "cloud": "20",
                        "uvIndex": "7",
                        "moonPhase": "Waxing",
                        "moonPhaseIcon": "801",
                    },
                    {"fxDate": "2026-07-01", "tempMax": "32"},
                ],
            }

        async def text(self):
            return ""

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def get(self, url, *, headers=None, params=None, proxy=None):
            calls.append((url, dict(params or {}), headers))
            return FakeResponse()

    monkeypatch.setattr(
        "magi.tools.providers.weather.qweather.aiohttp.ClientSession",
        FakeSession,
    )

    forecast = await QWeatherProvider()._query_forecast(
        location_id="101010100",
        api_key="key",
        api_host="devapi.qweather.com",
        lang="en",
        days=1,
        auth_headers={"X-QW-Api-Key": "key"},
    )

    assert len(forecast) == 1
    assert forecast[0]["date"] == "2026-06-30"
    assert forecast[0]["temp_max"] == "31"
    assert forecast[0]["condition_night"] == "Cloudy"
    assert forecast[0]["moon_phase_icon"] == "801"
    assert calls == [
        (
            "https://devapi.qweather.com/v7/weather/7d",
            {"location": "101010100", "lang": "en"},
            {"X-QW-Api-Key": "key"},
        )
    ]


@pytest.mark.asyncio
async def test_qweather_logs_omit_location_when_content_logging_is_disabled(
    monkeypatch,
    caplog,
):
    private_location = "private location from conversation"

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def json(self):
            return {"code": "200", "location": [{"id": "101010100"}]}

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def get(self, url, *, headers=None, params=None, proxy=None):
            return FakeResponse()

    monkeypatch.setattr(qweather_module.aiohttp, "ClientSession", FakeSession)
    monkeypatch.setattr(
        qweather_module,
        "full_content_logging_enabled",
        lambda: False,
    )

    with caplog.at_level("INFO", logger=qweather_module.logger.name):
        result = await QWeatherProvider()._resolve_location(
            location=private_location,
            api_key="key",
            api_host="devapi.qweather.com",
        )

    assert result == "101010100"
    assert private_location not in caplog.text
    assert f"location_chars={len(private_location)}" in caplog.text
