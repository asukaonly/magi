"""
QWeather Provider

Query weather using QWeather (和风天气) API.
"""
import aiohttp
from typing import Dict, Any, Optional

from ..base import Provider, ProviderConfig


class QWeatherProvider(Provider):
    """QWeather (和风天气) API provider."""

    DEFAULT_API_HOST = "devapi.qweather.com"

    @property
    def name(self) -> str:
        return "qweather"

    @property
    def display_name(self) -> str:
        return "QWeather (和风天气)"

    def is_ready(self, config: ProviderConfig) -> bool:
        """Check if QWeather API key is configured."""
        return bool(config.api_key)

    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig
    ) -> Dict[str, Any]:
        """
        Execute QWeather API call.

        Args:
            params: Must contain 'location', optional 'lang'
            config: Must contain 'api_key', optional 'base_url'

        Returns:
            Dict with weather data
        """
        location = params["location"]
        lang = params.get("lang", "zh")

        if not config.api_key:
            raise ValueError("QWeather API key not configured")

        api_host = config.base_url or self.DEFAULT_API_HOST

        # First, resolve location to LocationID if it's a city name
        location_id = await self._resolve_location(location, config.api_key, api_host)

        # Query weather
        weather_data = await self._query_weather(location_id, config.api_key, api_host, lang)

        return {
            "location": location,
            "location_id": location_id,
            "weather": weather_data,
            "provider": self.name,
        }

    async def _resolve_location(
        self,
        location: str,
        api_key: str,
        api_host: str
    ) -> str:
        """
        Resolve location to LocationID.

        If location looks like coordinates, return as-is.
        Otherwise, use GeoAPI to find the LocationID.
        """
        # Check if location is already coordinates (contains comma and numbers)
        if "," in location:
            parts = location.split(",")
            if len(parts) == 2:
                try:
                    float(parts[0].strip())
                    float(parts[1].strip())
                    # It's coordinates, return as-is
                    return location
                except ValueError:
                    pass

        # Use GeoAPI to find LocationID
        url = f"https://{api_host}/v2/city/lookup"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"location": location, "number": 1}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"GeoAPI error: {response.status} - {error_text}")

                data = await response.json()

        if data.get("code") != "200":
            raise Exception(f"Failed to resolve location: {data.get('message', 'Unknown error')}")

        locations = data.get("location", [])
        if not locations:
            raise Exception(f"Location not found: {location}")

        return locations[0].get("id", location)

    async def _query_weather(
        self,
        location_id: str,
        api_key: str,
        api_host: str,
        lang: str
    ) -> Dict[str, Any]:
        """Query current weather from QWeather API."""
        url = f"https://{api_host}/v7/weather/now"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {
            "location": location_id,
            "lang": lang,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Weather API error: {response.status} - {error_text}")

                data = await response.json()

        if data.get("code") != "200":
            raise Exception(f"Weather API returned error code: {data.get('code')}")

        now = data.get("now", {})

        return {
            "observation_time": now.get("obsTime"),
            "temperature": now.get("temp"),
            "feels_like": now.get("feelsLike"),
            "condition": now.get("text"),
            "icon_code": now.get("icon"),
            "wind_direction": now.get("windDir"),
            "wind_scale": now.get("windScale"),
            "wind_speed": now.get("windSpeed"),
            "humidity": now.get("humidity"),
            "precipitation": now.get("precip"),
            "pressure": now.get("pressure"),
            "visibility": now.get("vis"),
            "cloud_cover": now.get("cloud"),
            "dew_point": now.get("dew"),
            "update_time": data.get("updateTime"),
        }

    def get_config_schema(self) -> Dict[str, Any]:
        """Return QWeather-specific config schema."""
        return {
            "api_key": {
                "type": "string",
                "description": "QWeather API key (get from https://dev.qweather.com/)",
                "required": True,
            },
            "base_url": {
                "type": "string",
                "description": "API host (default: devapi.qweather.com, use api.qweather.com for paid plans)",
                "required": False,
            },
        }
