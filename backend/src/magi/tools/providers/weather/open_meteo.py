"""Open-Meteo weather provider."""

from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp

from ..base import Provider, ProviderConfig


class OpenMeteoProvider(Provider):
    """Keyless global weather provider backed by Open-Meteo."""

    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    TIMEOUT_SECONDS = 15

    _CONDITIONS = {
        "en": {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            56: "Light freezing drizzle",
            57: "Dense freezing drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            66: "Light freezing rain",
            67: "Heavy freezing rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            77: "Snow grains",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            85: "Slight snow showers",
            86: "Heavy snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail",
        },
        "zh": {
            0: "晴",
            1: "大部晴朗",
            2: "局部多云",
            3: "阴",
            45: "雾",
            48: "雾凇",
            51: "小毛毛雨",
            53: "中等毛毛雨",
            55: "浓毛毛雨",
            56: "小冻毛毛雨",
            57: "强冻毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            66: "小冻雨",
            67: "强冻雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "雪粒",
            80: "小阵雨",
            81: "中等阵雨",
            82: "强阵雨",
            85: "小阵雪",
            86: "强阵雪",
            95: "雷暴",
            96: "伴小冰雹雷暴",
            99: "伴强冰雹雷暴",
        },
    }

    @property
    def name(self) -> str:
        return "openmeteo"

    @property
    def display_name(self) -> str:
        return "Open-Meteo"

    def is_ready(self, config: ProviderConfig) -> bool:
        """Open-Meteo does not require credentials."""
        _ = config
        return True

    async def execute(self, params: Dict[str, Any], config: ProviderConfig) -> Dict[str, Any]:
        location = str(params["location"]).strip()
        lang = "zh" if str(params.get("lang", "en")).strip().lower().startswith("zh") else "en"
        mode = str(params.get("mode", "current")).strip().lower()
        if mode not in {"current", "forecast"}:
            raise ValueError("Invalid mode. Use 'current' or 'forecast'.")

        days = max(1, min(int(params.get("days", 3) or 3), 7))
        proxy_url = str(params.get("proxy_url") or "").strip() or None
        forecast_url = str(config.base_url or "").strip() or self.FORECAST_URL

        timeout = aiohttp.ClientTimeout(total=self.TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            resolved = await self._resolve_location(session, location, lang, proxy_url)
            payload = await self._fetch_forecast(
                session=session,
                url=forecast_url,
                latitude=resolved["latitude"],
                longitude=resolved["longitude"],
                mode=mode,
                days=days,
                proxy_url=proxy_url,
            )

        result: Dict[str, Any] = {
            "location": resolved,
            "mode": mode,
            "provider": self.name,
        }
        if mode == "forecast":
            result["days"] = days
            result["forecast"] = self._normalize_daily(payload, days, lang)
        else:
            result["weather"] = self._normalize_current(payload, lang)
        return result

    async def _resolve_location(
        self,
        session: aiohttp.ClientSession,
        location: str,
        lang: str,
        proxy_url: Optional[str],
    ) -> Dict[str, Any]:
        coordinates = self._parse_coordinates(location)
        if coordinates is not None:
            latitude, longitude = coordinates
            return {
                "name": location,
                "latitude": latitude,
                "longitude": longitude,
                "country": "",
                "admin1": "",
            }

        params = {
            "name": location,
            "count": 1,
            "language": lang,
            "format": "json",
        }
        async with session.get(self.GEOCODING_URL, params=params, proxy=proxy_url) as response:
            if response.status != 200:
                body = await response.text()
                raise Exception(f"Open-Meteo geocoding error: {response.status} - {body[:300]}")
            data = await response.json()

        results = data.get("results") or []
        if not results:
            raise Exception(f"Location not found: {location}")
        item = results[0]
        return {
            "name": item.get("name") or location,
            "latitude": float(item["latitude"]),
            "longitude": float(item["longitude"]),
            "country": item.get("country") or "",
            "admin1": item.get("admin1") or "",
        }

    async def _fetch_forecast(
        self,
        *,
        session: aiohttp.ClientSession,
        url: str,
        latitude: float,
        longitude: float,
        mode: str,
        days: int,
        proxy_url: Optional[str],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "timezone": "auto",
        }
        if mode == "forecast":
            params.update(
                {
                    "daily": ",".join(
                        [
                            "weather_code",
                            "temperature_2m_max",
                            "temperature_2m_min",
                            "precipitation_sum",
                            "wind_speed_10m_max",
                        ]
                    ),
                    "forecast_days": days,
                }
            )
        else:
            params.update(
                {
                    "current": ",".join(
                        [
                            "temperature_2m",
                            "relative_humidity_2m",
                            "apparent_temperature",
                            "precipitation",
                            "weather_code",
                            "wind_speed_10m",
                            "wind_direction_10m",
                        ]
                    )
                }
            )

        async with session.get(url, params=params, proxy=proxy_url) as response:
            if response.status != 200:
                body = await response.text()
                raise Exception(f"Open-Meteo forecast error: {response.status} - {body[:300]}")
            return await response.json()

    def _normalize_current(self, payload: Dict[str, Any], lang: str) -> Dict[str, Any]:
        current = payload.get("current") or {}
        code = self._safe_int(current.get("weather_code"))
        return {
            "observation_time": current.get("time"),
            "temperature": self._safe_float(current.get("temperature_2m")),
            "feels_like": self._safe_float(current.get("apparent_temperature")),
            "condition": self._condition_text(code, lang),
            "weather_code": code,
            "humidity": self._safe_float(current.get("relative_humidity_2m")),
            "precipitation": self._safe_float(current.get("precipitation")),
            "wind_speed": self._safe_float(current.get("wind_speed_10m")),
            "wind_direction": self._safe_float(current.get("wind_direction_10m")),
        }

    def _normalize_daily(self, payload: Dict[str, Any], days: int, lang: str) -> list[Dict[str, Any]]:
        daily = payload.get("daily") or {}
        dates = daily.get("time") or []
        codes = daily.get("weather_code") or []
        temp_max = daily.get("temperature_2m_max") or []
        temp_min = daily.get("temperature_2m_min") or []
        precipitation = daily.get("precipitation_sum") or []
        wind_speed = daily.get("wind_speed_10m_max") or []

        forecast: list[Dict[str, Any]] = []
        for idx, date_value in enumerate(dates[:days]):
            code = self._safe_int(codes[idx] if idx < len(codes) else None)
            forecast.append(
                {
                    "date": date_value,
                    "condition_day": self._condition_text(code, lang),
                    "weather_code": code,
                    "temp_max": self._safe_float(temp_max[idx] if idx < len(temp_max) else None),
                    "temp_min": self._safe_float(temp_min[idx] if idx < len(temp_min) else None),
                    "precipitation": self._safe_float(
                        precipitation[idx] if idx < len(precipitation) else None
                    ),
                    "wind_speed_day": self._safe_float(
                        wind_speed[idx] if idx < len(wind_speed) else None
                    ),
                }
            )
        return forecast

    def _condition_text(self, code: Optional[int], lang: str) -> str:
        if code is None:
            return "Unknown" if lang == "en" else "未知"
        return self._CONDITIONS.get(lang, self._CONDITIONS["en"]).get(
            code,
            "Unknown" if lang == "en" else "未知",
        )

    @staticmethod
    def _parse_coordinates(location: str) -> Optional[tuple[float, float]]:
        if "," not in location:
            return None
        parts = location.split(",", 1)
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            return None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def get_config_schema(self) -> Dict[str, Any]:
        """Return Open-Meteo config schema."""
        return {
            "base_url": {
                "type": "string",
                "description": "Open-Meteo forecast endpoint override (optional)",
                "required": False,
            }
        }
