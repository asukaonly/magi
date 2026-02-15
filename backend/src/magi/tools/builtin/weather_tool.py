"""
Weather Tool - Query weather using QWeather (和风天气) API
"""
import os
import aiohttp
from typing import Dict, Any, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType


class WeatherTool(Tool):
    """
    Weather Tool

    Query weather information using QWeather (和风天气) API.
    Supports querying by city name or coordinates.
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="weather",
            description="Query weather information for a specific location. Returns current weather including temperature, humidity, wind, and more.",
            category="information",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="location",
                    type=ParameterType.STRING,
                    description="Location to query. Can be a city name (e.g., 'Beijing', '上海') or coordinates as 'longitude,latitude' (e.g., '116.41,39.92')",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ParameterType.STRING,
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
            api_key = os.environ.get("QWEATHER_API_KEY")
            api_host = os.environ.get("QWEATHER_API_HOST", "devapi.qweather.com")

            if not api_key:
                return ToolResult(
                    success=False,
                    error="QWEATHER_API_KEY environment variable not set. Please get your API key from https://dev.qweather.com/",
                    error_code="MISSING_API_KEY",
                )

            # First, try to resolve location to LocationID if it's a city name
            location_id = await self._resolve_location(location, api_key, api_host)

            # Query weather
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
                error_code="WEATHER_QUERY_ERROR",
            )

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
        """Query current weather from QWeather API"""
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
