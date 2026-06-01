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


class NominatimClient:
    """Reverse-geocode (lat, lng) → city/region/country, with cache."""

    def __init__(self, *, cache: PlaceGeocodeCache) -> None:
        self._cache = cache

    async def reverse(
        self, lat: float, lng: float,
    ) -> Optional[dict[str, Optional[str]]]:
        """Return ``{city, region, country, poi_name}`` for the coordinate.

        Hits the cache first; on miss, calls Nominatim and writes back.
        Returns ``None`` on network failure (and does not cache the absence
        so a transient outage doesn't poison the cache).
        """
        cached = await self._cache.lookup(lat, lng)
        if cached is not None:
            return {
                "city": cached.get("city"),
                "region": cached.get("region"),
                "country": cached.get("country"),
                "poi_name": cached.get("poi_name"),
            }

        try:
            async with httpx.AsyncClient(
                timeout=NOMINATIM_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh,en"},
            ) as client:
                response = await client.get(
                    NOMINATIM_URL,
                    params={
                        "format": "jsonv2",
                        "lat": str(lat),
                        "lon": str(lng),
                        "zoom": "14",  # neighborhood-ish
                        "addressdetails": "1",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("nominatim reverse failed", error=str(exc))
            return None

        if not isinstance(payload, dict):
            return None
        addr = payload.get("address") or {}

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

        await self._cache.put(
            lat, lng,
            city=_str_or_none(city),
            region=_str_or_none(region),
            country=_str_or_none(country),
            poi_name=_str_or_none(poi_name),
        )

        return {
            "city": _str_or_none(city),
            "region": _str_or_none(region),
            "country": _str_or_none(country),
            "poi_name": _str_or_none(poi_name),
        }


def _str_or_none(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
