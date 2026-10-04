"""Provider readiness requirements exposed in tool settings."""

from magi.api.routers.tools import _build_tool_config_response
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.weather.open_meteo import OpenMeteoProvider
from magi.tools.providers.weather.qweather import QWeatherProvider


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
