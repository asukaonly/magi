"""Thin Nominatim reverse-geocode client with cache pass-through.

OpenStreetMap's Nominatim is free + open but rate-limited to 1 req/sec
per IP. We always go through the ``PlaceGeocodeCache`` first to dedupe
calls for coordinates we've already resolved.
"""

from __future__ import annotations

from typing import Optional

import httpx

from ..core.logger import get_logger
from .store import PlaceGeocodeCache

logger = get_logger("magi.location.nominatim")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_TIMEOUT = 8.0
# Per Nominatim usage policy, must identify the app.
USER_AGENT = "magi-agent/0.1 (https://github.com/asukaonly/magi)"
LocationLabels = dict[str, Optional[str]]


class NominatimClient:
    """Reverse-geocode (lat, lng) → city/region/country, with cache."""

    def __init__(self, *, cache: PlaceGeocodeCache) -> None:
        self._cache = cache

    async def reverse(self, lat: float, lng: float) -> Optional[LocationLabels]:
        """Return ``{city, region, country, poi_name}`` for the coordinate.

        Hits the cache first; on miss, calls Nominatim and writes back.
        Returns ``None`` on network failure (and does not cache the absence
        so a transient outage doesn't poison the cache).
        """
        cached_labels = await self._cached_labels(lat, lng)
        if cached_labels is not None:
            return cached_labels

        payload = await self._fetch_reverse_payload(lat, lng)
        if payload is None:
            return None
        labels = self._labels_from_payload(payload)
        if labels is None:
            return None
        await self._cache_labels(lat, lng, labels)
        return labels

    async def _cached_labels(self, lat: float, lng: float) -> Optional[LocationLabels]:
        cached = await self._cache.lookup(lat, lng)
        if cached is None:
            return None
        return self._labels_from_cache(cached)

    @staticmethod
    def _labels_from_cache(cached: dict[str, object]) -> LocationLabels:
        return {
            "city": cached.get("city"),
            "region": cached.get("region"),
            "country": cached.get("country"),
            "poi_name": cached.get("poi_name"),
        }

    async def _fetch_reverse_payload(self, lat: float, lng: float) -> dict[str, object] | None:
        try:
            async with httpx.AsyncClient(
                timeout=NOMINATIM_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh,en"},
            ) as client:
                response = await client.get(NOMINATIM_URL, params=_reverse_params(lat, lng))
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("nominatim reverse failed", error=str(exc))
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _labels_from_payload(payload: dict[str, object]) -> LocationLabels | None:
        addr = payload.get("address") or {}
        if not isinstance(addr, dict):
            return None
        # Nominatim returns many keys; pick the most useful at the asked zoom.
        # Order tried for city: city > town > village > suburb > county.
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("suburb")
            or addr.get("county")
        )
        region = addr.get("state") or addr.get("region")
        country = addr.get("country")
        # POI hints — only fill if Nominatim actually pointed at something
        # specific (e.g. a named restaurant or building).
        poi_name = payload.get("name") or addr.get("amenity") or addr.get("shop")
        return {
            "city": _str_or_none(city),
            "region": _str_or_none(region),
            "country": _str_or_none(country),
            "poi_name": _str_or_none(poi_name),
        }

    async def _cache_labels(self, lat: float, lng: float, labels: LocationLabels) -> None:
        await self._cache.put(
            lat, lng,
            city=labels["city"],
            region=labels["region"],
            country=labels["country"],
            poi_name=labels["poi_name"],
        )


def _reverse_params(lat: float, lng: float) -> dict[str, str]:
    return {
        "format": "jsonv2",
        "lat": str(lat),
        "lon": str(lng),
        "zoom": "14",  # neighborhood-ish
        "addressdetails": "1",
    }


def _str_or_none(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
