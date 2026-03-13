"""
Tests for QWeather provider error message mapping.
"""
from magi.tools.providers.weather.qweather import QWeatherProvider


def test_format_api_error_returns_base_url_hint_for_invalid_host():
    provider = QWeatherProvider()
    body = (
        '{"error":{"status":403,"type":"https://dev.qweather.com/docs/resource/error-code/#invalid-host",'
        '"title":"Invalid Host","detail":"An invalid or unauthorized API Host."}}'
    )

    message = provider._format_api_error(
        api_name="GeoAPI",
        status=403,
        url="https://devapi.qweather.com/geo/v2/city/lookup",
        params={"location": "Hangzhou", "number": 1},
        error_text=body,
    )

    assert (
        message
        == "QWeather requires a configured base URL. Please get it from https://console.qweather.com/setting."
    )


def test_format_api_error_keeps_diagnostics_for_non_host_errors():
    provider = QWeatherProvider()

    message = provider._format_api_error(
        api_name="GeoAPI",
        status=500,
        url="https://devapi.qweather.com/geo/v2/city/lookup",
        params={"location": "Hangzhou", "number": 1},
        error_text='{"error":{"title":"Internal Error"}}',
    )

    assert message.startswith("GeoAPI API error: 500 | url=https://devapi.qweather.com/geo/v2/city/lookup")
    assert "params={'location': 'Hangzhou', 'number': 1}" in message
