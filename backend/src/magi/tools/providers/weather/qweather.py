"""
QWeather Provider

Query weather using QWeather (和风天气) API.
"""
import aiohttp
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import logging
import json

from ..base import Provider, ProviderConfig

logger = logging.getLogger(__name__)


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
        return bool((config.api_key or "").strip())

    def _normalize_api_host(self, raw_value: Optional[str]) -> str:
        """Normalize endpoint value to host-only format."""
        text = (raw_value or "").strip()
        if not text:
            return ""

        if "://" in text:
            parsed = urlparse(text)
            text = parsed.netloc or parsed.path

        text = text.strip().strip("/")
        if "/" in text:
            text = text.split("/", 1)[0]
        return text

    def _is_jwt_token(self, credential: str) -> bool:
        """Heuristic check whether credential is a JWT token."""
        return credential.count(".") == 2

    def _build_auth_headers(self, credential: str) -> tuple[Dict[str, str], str]:
        """
        Build auth headers for QWeather.

        - API KEY: use X-QW-Api-Key header
        - JWT: use Authorization Bearer header
        """
        if self._is_jwt_token(credential):
            return {"Authorization": f"Bearer {credential}"}, "jwt"
        return {"X-QW-Api-Key": credential}, "api_key"

    def _format_api_error(
        self,
        api_name: str,
        status: int,
        url: str,
        params: Dict[str, Any],
        error_text: str,
    ) -> str:
        """
        Format provider error message with user-facing hint when host is invalid.

        QWeather may return host-related errors in different formats. When detected,
        return a clear remediation message instead of a raw API payload dump.
        """
        raw_text = (error_text or "").strip()
        lowered_fragments = [raw_text.lower()]

        try:
            payload = json.loads(raw_text)
        except Exception:
            payload = None

        if isinstance(payload, dict):
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                for key in ("type", "title", "detail"):
                    value = error_obj.get(key)
                    if isinstance(value, str):
                        lowered_fragments.append(value.lower())

        combined = " ".join(lowered_fragments)
        host_error_markers = (
            "invalid-host",
            "invalid_host",
            "invaild-host",
            "unauthorized api host",
            "invalid or unauthorized api host",
        )
        if any(marker in combined for marker in host_error_markers):
            return (
                "QWeather requires a configured base URL. "
                "Please get it from https://console.qweather.com/setting."
            )

        return (
            f"{api_name} API error: {status} | url={url} | params={params} | "
            f"body={raw_text[:300]}"
        )

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
        mode = str(params.get("mode", "current")).strip().lower()
        if mode not in {"current", "forecast"}:
            raise ValueError("Invalid mode. Use 'current' or 'forecast'.")
        days = 3
        if mode == "forecast":
            days = int(params.get("days", 3) or 3)
        proxy_url = str(params.get("proxy_url") or "").strip() or None

        if not config.api_key:
            raise ValueError("QWeather API key not configured")
        credential = str(config.api_key).strip()
        if not credential:
            raise ValueError("QWeather API key not configured")
        auth_headers, auth_mode = self._build_auth_headers(credential)

        api_host = self._normalize_api_host(config.base_url) or self.DEFAULT_API_HOST
        logger.info(
            "[QWeather] execute | location=%s | lang=%s | api_host=%s | auth_mode=%s",
            location,
            lang,
            api_host,
            auth_mode,
        )

        # First, resolve location to LocationID if it's a city name
        location_id = await self._resolve_location(location, credential, api_host, proxy_url)

        if mode == "forecast":
            forecast_data = await self._query_forecast(
                location_id=location_id,
                api_key=credential,
                api_host=api_host,
                lang=lang,
                days=days,
                auth_headers=auth_headers,
                proxy_url=proxy_url,
            )
            return {
                "location": location,
                "location_id": location_id,
                "mode": "forecast",
                "days": days,
                "forecast": forecast_data,
                "provider": self.name,
            }

        # Default mode: current weather
        weather_data = await self._query_weather(
            location_id=location_id,
            api_key=credential,
            api_host=api_host,
            lang=lang,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )
        return {
            "location": location,
            "location_id": location_id,
            "mode": "current",
            "weather": weather_data,
            "provider": self.name,
        }

    async def _resolve_location(
        self,
        location: str,
        api_key: str,
        api_host: str,
        proxy_url: Optional[str] = None,
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

        # Use GeoAPI to find LocationID.
        # QWeather GeoAPI endpoint requires /geo prefix.
        url = f"https://{api_host}/geo/v2/city/lookup"
        headers, _ = self._build_auth_headers(api_key)
        params = {"location": location, "number": 1}
        logger.info(
            "[QWeather] Geo lookup request | url=%s | params=%s",
            url,
            params,
        )

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get(url, headers=headers, params=params, proxy=proxy_url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(
                        "[QWeather] Geo lookup failed | status=%s | url=%s | params=%s | body=%s",
                        response.status,
                        url,
                        params,
                        error_text[:300],
                    )
                    raise Exception(
                        self._format_api_error(
                            api_name="GeoAPI",
                            status=response.status,
                            url=url,
                            params=params,
                            error_text=error_text,
                        )
                    )

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
        lang: str,
        auth_headers: Optional[Dict[str, str]] = None,
        proxy_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query current weather from QWeather API."""
        url = f"https://{api_host}/v7/weather/now"
        headers = auth_headers or self._build_auth_headers(api_key)[0]
        params = {
            "location": location_id,
            "lang": lang,
        }
        logger.info(
            "[QWeather] Weather request | url=%s | params=%s",
            url,
            params,
        )

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get(url, headers=headers, params=params, proxy=proxy_url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(
                        "[QWeather] Weather request failed | status=%s | url=%s | params=%s | body=%s",
                        response.status,
                        url,
                        params,
                        error_text[:300],
                    )
                    raise Exception(
                        self._format_api_error(
                            api_name="Weather",
                            status=response.status,
                            url=url,
                            params=params,
                            error_text=error_text,
                        )
                    )

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

    async def _query_forecast(
        self,
        location_id: str,
        api_key: str,
        api_host: str,
        lang: str,
        days: int,
        auth_headers: Optional[Dict[str, str]] = None,
        proxy_url: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        """Query daily forecast from QWeather API."""
        url = f"https://{api_host}/v7/weather/7d"
        headers = auth_headers or self._build_auth_headers(api_key)[0]
        params = {
            "location": location_id,
            "lang": lang,
        }
        logger.info(
            "[QWeather] Forecast request | url=%s | params=%s | days=%s",
            url,
            params,
            days,
        )

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get(url, headers=headers, params=params, proxy=proxy_url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.warning(
                        "[QWeather] Forecast request failed | status=%s | url=%s | params=%s | body=%s",
                        response.status,
                        url,
                        params,
                        error_text[:300],
                    )
                    raise Exception(
                        self._format_api_error(
                            api_name="Forecast",
                            status=response.status,
                            url=url,
                            params=params,
                            error_text=error_text,
                        )
                    )

                data = await response.json()

        if data.get("code") != "200":
            raise Exception(f"Forecast API returned error code: {data.get('code')}")

        daily_items = data.get("daily", [])[:days]
        forecast: list[Dict[str, Any]] = []
        for item in daily_items:
            forecast.append(
                {
                    "date": item.get("fxDate"),
                    "sunrise": item.get("sunrise"),
                    "sunset": item.get("sunset"),
                    "temp_max": item.get("tempMax"),
                    "temp_min": item.get("tempMin"),
                    "condition_day": item.get("textDay"),
                    "condition_night": item.get("textNight"),
                    "icon_day": item.get("iconDay"),
                    "icon_night": item.get("iconNight"),
                    "wind_dir_day": item.get("windDirDay"),
                    "wind_scale_day": item.get("windScaleDay"),
                    "wind_speed_day": item.get("windSpeedDay"),
                    "wind_dir_night": item.get("windDirNight"),
                    "wind_scale_night": item.get("windScaleNight"),
                    "wind_speed_night": item.get("windSpeedNight"),
                    "humidity": item.get("humidity"),
                    "precipitation": item.get("precip"),
                    "pressure": item.get("pressure"),
                    "visibility": item.get("vis"),
                    "cloud_cover": item.get("cloud"),
                    "uv_index": item.get("uvIndex"),
                    "moon_phase": item.get("moonPhase"),
                    "moon_phase_icon": item.get("moonPhaseIcon"),
                }
            )

        return forecast

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
