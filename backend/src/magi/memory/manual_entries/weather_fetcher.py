"""Ambient weather lookup for manual memory entries.

We hit Open-Meteo (no API key, generous free tier) once per entry create
or after the user edits the entry's location / event_at. The fetcher is
best-effort: any failure (network down, no usable coords, event too far
in the past) returns ``None`` and the caller leaves the chip empty.

Cache: small in-process dict keyed by
``(round(lat,1), round(lng,1), YYYY-MM-DDTHH)`` so the same hour at the
same ~10km grid never costs more than one HTTP round-trip across all
entries. Open-Meteo's quota is high enough that we don't *need* the cache,
but it keeps idle Magi instances polite and makes the test suite
deterministic.

WMO code → emoji mapping is exported alongside the fetcher so the
frontend can stay in sync via a small lookup table (duplicated, not
imported across the network boundary — keeping the contract trivial).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ...core.logger import get_logger

logger = get_logger("magi.memory.manual_entries.weather")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT_SECONDS = 4.0
# Forecast endpoint supports `past_days` up to 92, but the data quality
# degrades for older dates. 7 days back covers ~all manual-entry use
# (people backdate to "last week" at the outside) and avoids us silently
# falling back to climatology for ancient entries.
PAST_DAYS_SUPPORTED = 7
# Coordinate granularity for the cache key — 0.1° ≈ 11km, plenty for
# weather, which doesn't vary inside a city.
CACHE_GRID_DECIMALS = 1
CACHE_MAX_ENTRIES = 256


# WMO weather code → category label. Same mapping as the frontend; keep
# both sides updated together when adding codes. Categories collapse
# similar codes (51/53/55 = drizzle of varying intensity → one bucket)
# because the chip's job is "give me a one-glance sense of the weather",
# not "exact intensity".
WMO_CATEGORY: dict[int, str] = {
    0: "clear",
    1: "mostly_clear",
    2: "partly_cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    56: "drizzle",
    57: "drizzle",
    61: "rain",
    63: "rain",
    65: "rain",
    66: "rain",
    67: "rain",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "showers",
    81: "showers",
    82: "showers",
    85: "snow_showers",
    86: "snow_showers",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}


def weather_category(code: int) -> str:
    """Map a WMO code to a stable short category string.

    Unknown codes fall back to ``"unknown"`` so the frontend can decide
    whether to render a generic chip or hide it — we don't drop the row.
    """
    return WMO_CATEGORY.get(int(code), "unknown")


def _cache_key(lat: float, lng: float, event_at: float) -> tuple[float, float, str]:
    """Cache key truncates lat/lng to ~10km grid and event_at to the hour.

    Hour-bucketing matches Open-Meteo's hourly resolution — finer would
    just multiply cache entries for no gain.
    """
    lat_r = round(lat, CACHE_GRID_DECIMALS)
    lng_r = round(lng, CACHE_GRID_DECIMALS)
    dt = datetime.fromtimestamp(event_at, tz=timezone.utc)
    hour_iso = dt.strftime("%Y-%m-%dT%H")
    return (lat_r, lng_r, hour_iso)


class WeatherFetcher:
    """Open-Meteo client + small LRU cache.

    Threadsafety: not. Single event loop only. The cache is a plain dict
    behind ``_lock``; if the fetcher is ever shared across loops the lock
    becomes the contention point but for now there's exactly one.
    """

    def __init__(
        self,
        *,
        url: str = OPEN_METEO_URL,
        timeout: float = OPEN_METEO_TIMEOUT_SECONDS,
        client_factory: Optional[Any] = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        # `client_factory` lets tests inject a stub without monkey-patching
        # httpx — call signature is `() -> httpx.AsyncClient`. Production
        # callers stick with the default.
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self._timeout)
        )
        self._cache: "OrderedDict[tuple, Optional[dict]]" = OrderedDict()
        self._lock = asyncio.Lock()
        self._clear_generation = 0

    async def clear(self) -> int:
        """Drop cached location lookups and fence in-flight fetch results."""
        async with self._lock:
            cleared = len(self._cache)
            self._clear_generation += 1
            self._cache.clear()
            return cleared

    async def fetch(
        self, *, lat: float, lng: float, event_at: float,
    ) -> Optional[dict]:
        """Resolve ``{code, temp_c, fetched_at}`` for the given coords + time.

        Returns ``None`` when:
          - event_at is more than PAST_DAYS_SUPPORTED days in the past
          - event_at is in the future beyond the forecast horizon (~16d)
          - Open-Meteo can't be reached or returns malformed data
        """
        now = _now()
        days_back = (now - event_at) / 86400.0
        if days_back > PAST_DAYS_SUPPORTED + 1:
            # Older than the supported window; skip rather than fall back
            # to the historical archive (different API, deferred to B-2).
            return None
        if event_at > now + 86400 * 14:
            return None

        key = _cache_key(lat, lng, event_at)
        async with self._lock:
            expected_generation = self._clear_generation
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

        result = await self._do_fetch(lat, lng, event_at)

        async with self._lock:
            if expected_generation != self._clear_generation:
                return result
            self._cache[key] = result
            # Bound the cache. Open-Meteo isn't a heavy server but our
            # process memory shouldn't grow unboundedly across days of
            # use. LRU eviction = drop the oldest insertion.
            while len(self._cache) > CACHE_MAX_ENTRIES:
                self._cache.popitem(last=False)
        return result

    async def _do_fetch(
        self, lat: float, lng: float, event_at: float,
    ) -> Optional[dict]:
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lng:.4f}",
            "hourly": "temperature_2m,weather_code",
            "past_days": str(PAST_DAYS_SUPPORTED),
            "forecast_days": "1",
            "timezone": "UTC",
        }
        try:
            async with self._client_factory() as client:
                response = await client.get(self._url, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 — symmetric "give up gracefully"
            logger.warning("Open-Meteo fetch failed", error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            return None
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        codes = hourly.get("weather_code") or []
        if not (isinstance(times, list) and isinstance(temps, list) and isinstance(codes, list)):
            return None
        if not times or len(times) != len(temps) or len(times) != len(codes):
            return None

        idx = _nearest_hour_index(times, event_at)
        if idx is None:
            return None
        try:
            temp_c = float(temps[idx])
            code = int(codes[idx])
        except (TypeError, ValueError):
            return None

        return {
            "code": code,
            "temp_c": round(temp_c, 1),
            "fetched_at": _now(),
        }


def _now() -> float:
    """Wrapped so tests can monkeypatch."""
    import time
    return time.time()


def _nearest_hour_index(times: list[str], event_at: float) -> Optional[int]:
    """Return the index in ``times`` whose ISO string is closest to event_at.

    Open-Meteo returns hourly ISO strings without timezone offset when we
    request ``timezone=UTC``; treat them as UTC. We do a linear scan
    because the lists are at most 192 entries (8 days × 24h) and a binary
    search would obfuscate for negligible gain.
    """
    target = event_at
    best_idx: Optional[int] = None
    best_delta = float("inf")
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta = abs(dt.timestamp() - target)
        if delta < best_delta:
            best_delta = delta
            best_idx = i
    # If the closest hour is >2h off, give up — usually means the event
    # falls outside the requested window.
    if best_idx is None or best_delta > 2 * 3600:
        return None
    return best_idx
