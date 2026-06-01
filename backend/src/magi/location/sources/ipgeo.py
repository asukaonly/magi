"""IP-geo location source — city-accuracy, no permission, single HTTP request.

Uses ``ipapi.co`` (free tier: 1000 req/day, no key). Returns city + region +
country + lat/lng. Falls back gracefully to "" on any failure — the
resolver treats no-samples as "next source please."
"""

from __future__ import annotations

import time
from typing import Optional

import httpx

from ...core.logger import get_logger
from ..models import LocationSample
from ..store import LocationSampleStore

logger = get_logger("magi.location.ipgeo")


# IP geo is the lowest-priority baseline source. It exists to ensure we
# always have *some* location signal for the Hero, even on machines with no
# WiFi adapter and no photo plugin.
IPGEO_PRIORITY = 10

# A single IP-geo answer is treated as valid for a day. IPs don't shift
# city level on the minute, and we poll at the same cadence.
IPGEO_VALIDITY_SECONDS = 24 * 60 * 60

IPAPI_URL = "https://ipapi.co/json/"
IPAPI_TIMEOUT_SECONDS = 8.0


class IPGeoLocationSource:
    """Reads previously-sampled ipgeo rows from storage.

    The scheduler is responsible for *writing* fresh samples via
    ``poll_and_persist``; this read-path is what the resolver calls during
    a viewport build.
    """

    source_name = "ipgeo"
    priority = IPGEO_PRIORITY
    validity_seconds = IPGEO_VALIDITY_SECONDS

    def __init__(self, *, store: LocationSampleStore) -> None:
        self._store = store

    async def query_samples(
        self, *, time_start: float, time_end: float,
    ) -> list[LocationSample]:
        # IP samples have a 24h validity, so a sample taken just before the
        # window can still contribute. Widen the read by validity to catch it.
        widened_start = time_start - self.validity_seconds
        all_samples = await self._store.query_window(
            time_start=widened_start, time_end=time_end, source=self.source_name,
        )
        # Drop the ones whose *validity* doesn't overlap the actual window.
        return [
            s for s in all_samples
            if s.sampled_at + self.validity_seconds >= time_start
            and s.sampled_at <= time_end
        ]

    async def poll_and_persist(self) -> Optional[LocationSample]:
        """Hit ipapi.co once and store the result. Returns the persisted
        sample, or None on failure (network, rate-limit, malformed JSON).
        """
        try:
            async with httpx.AsyncClient(timeout=IPAPI_TIMEOUT_SECONDS) as client:
                response = await client.get(IPAPI_URL)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # network / json / status — same treatment
            logger.warning("ipapi.co lookup failed", error=str(exc))
            return None

        if not isinstance(payload, dict):
            logger.warning("ipapi.co returned non-dict payload", payload=type(payload).__name__)
            return None

        # ipapi.co fields we care about (all strings except lat/lng):
        #   city, region, country_name, latitude, longitude
        city = _opt_str(payload.get("city"))
        region = _opt_str(payload.get("region"))
        country = _opt_str(payload.get("country_name"))
        lat = _opt_float(payload.get("latitude"))
        lng = _opt_float(payload.get("longitude"))

        if not city and not region and not country:
            # Likely rate-limited (ipapi returns 200 with an error field).
            logger.warning(
                "ipapi.co returned no usable labels",
                error=str(payload.get("reason") or payload.get("error") or "unknown"),
            )
            return None

        sample = LocationSample(
            sample_id="",  # store assigns
            source=self.source_name,
            sampled_at=time.time(),
            lat=lat,
            lng=lng,
            # ipapi accuracy is "city" — we record ~10km as a stand-in so the
            # accuracy_tier comparison treats it as the lowest tier.
            accuracy_m=10000.0,
            city=city,
            region=region,
            country=country,
            metadata={"provider": "ipapi.co"},
        )
        sample_id = await self._store.insert(sample)
        sample.sample_id = sample_id
        logger.info(
            "ipgeo sample stored", city=city, region=region, country=country,
        )
        return sample


def _opt_str(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _opt_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
