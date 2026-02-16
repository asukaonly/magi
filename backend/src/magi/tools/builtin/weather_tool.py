"""
Weather Tool - query weather using QWeather (and风days气) API
"""
import os
import aiohttp
from typing import Dict, Any, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, Parametertype


class WeatherTool(Tool):
    """
    Weather Tool

    query weather information using QWeather (and风days气) API.
    Supports querying by city name or coordinates.
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="weather",
            description="query weather information for a specific location. Returns current weather including temperature, humidity, wind, and more.",
            category="information",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="location",
                    type=Parametertype.strING,
                    description="Location to query. Can be a city name (e.g., 'Beijing', '上海') or coordinates as 'longitude,latitude' (e.g., '116.41,39.92')",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=Parametertype.strING,
                    description="Language for weather descriptions: 'zh' (Chinese, default), 'en' (English)",
                    required=False,
                    default="zh",
                    enum=["zh", "en"],
                ),
            ],
            examples=[
                {
                    "input": {"location": "Beijing"},
                    "output": "Returns current weather in Beijing",
                },
                {
                    "input": {"location": "上海", "lang": "zh"},
                    "output": "Returns current weather in Shanghai with Chinese descriptions",
                },
                {
                    "input": {"location": "116.41,39.92", "lang": "en"},
                    "output": "Returns current weather at specific coordinates with English descriptions",
                },
            ],
            timeout=15,
            retry_on_failure=True,
            max_retries=2,
            dangerous=False,
            tags=["weather", "information", "qweather"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute weather query"""
        location = parameters["location"]
        lang = parameters.get("lang", "zh")

        try:
            # Get API credentials
            api_key = os.environ.get("QWEATHER_API_key")
            api_host = os.environ.get("QWEATHER_API_host", "devapi.qweather.com")

            if not api_key:
                return ToolResult(
                    success=False,
                    error="QWEATHER_API_key environment variable not set. Please get your API key from https://dev.qweather.com/",
                    error_code="MISSING_API_key",
                )

            # First, try to resolve location to Locationid if it's a city name
            location_id = await self._resolve_location(location, api_key, api_host)

            # query weather
            weather_data = await self._query_weather(location_id, api_key, api_host, lang)

            return ToolResult(
                success=True,
                data={
                    "location": location,
                    "location_id": location_id,
                    "weather": weather_data,
                },
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="WEATHER_QUERY_error",
            )

    async def _resolve_location(
        self,
        location: str,
        api_key: str,
        api_host: str
    ) -> str:
        """
        Resolve location to Locationid.
        If location looks like coordinates, return as-is.
        Otherwise, use GeoAPI to find the Locationid.
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
                except Valueerror:
                    pass

        # Use GeoAPI to find Locationid
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
            raise Exception(f"Failed to resolve location: {data.get('message', 'Unknotttwn error')}")

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
        """query current weather from QWeather API"""
        url = f"https://{api_host}/v7/weather/notttw"
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

        notttw = data.get("notttw", {})

        return {
            "observation_time": notttw.get("obsTime"),
            "temperature": notttw.get("temp"),
            "feels_like": notttw.get("feelsLike"),
            "condition": notttw.get("text"),
            "icon_code": notttw.get("icon"),
            "wind_direction": notttw.get("windDir"),
            "wind_scale": notttw.get("windScale"),
            "wind_speed": notttw.get("windSpeed"),
            "humidity": notttw.get("humidity"),
            "precipitation": notttw.get("precip"),
            "pressure": notttw.get("pressure"),
            "visibility": notttw.get("vis"),
            "cloud_cover": notttw.get("cloud"),
            "dew_point": notttw.get("dew"),
            "update_time": data.get("updateTime"),
        }
