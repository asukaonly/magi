"""WiFi-scan-based location source.

Scans nearby WiFi APs → Mozilla Location Service for coords → Nominatim for
reverse-geocoded labels → persists as a location_sample with source='wifi'.

Priority sits between Photo (highest) and IPGeo (lowest). Validity window
is 2 hours — WiFi position is stable while you stay put but should expire
quickly so a fresh scan after a move dominates.
"""

from __future__ import annotations

import time
from typing import Optional

from ...core.logger import get_logger
from ..models import LocationSample
from ..nominatim import NominatimClient
from ..store import LocationSampleStore
from ..wifi_scanner import mozilla_locate, scan_wifi

logger = get_logger("magi.location.wifi")

WIFI_PRIORITY = 50
WIFI_VALIDITY_SECONDS = 2 * 60 * 60  # 2 hours


class WiFiLocationSource:
    """Reads previously-stored WiFi samples for the resolver; the scheduler
    writes them via ``poll_and_persist`` on its own cadence."""

    source_name = "wifi"
    priority = WIFI_PRIORITY
    validity_seconds = WIFI_VALIDITY_SECONDS

    def __init__(
        self,
        *,
        store: LocationSampleStore,
        nominatim: NominatimClient,
    ) -> None:
        self._store = store
        self._nominatim = nominatim

    async def query_samples(
        self, *, time_start: float, time_end: float,
    ) -> list[LocationSample]:
        widened_start = time_start - self.validity_seconds
        all_samples = await self._store.query_window(
            time_start=widened_start, time_end=time_end, source=self.source_name,
        )
        return [
            s for s in all_samples
            if s.sampled_at + self.validity_seconds >= time_start
            and s.sampled_at <= time_end
        ]

    async def poll_and_persist(self) -> Optional[LocationSample]:
        """Single scan → Mozilla → Nominatim → store. Returns sample or None."""
        aps = await scan_wifi()
        if not aps:
            return None

        fix = await mozilla_locate(aps)
        if fix is None:
            return None

        labels = await self._nominatim.reverse(fix.lat, fix.lng)
        if labels is None:
            # Mozilla gave us coords but reverse-geocode failed. Still
            # persist the lat/lng — the resolver can use empty labels as a
            # signal of "WiFi positioned but no city name" (rare case).
            labels = {"city": None, "region": None, "country": None, "poi_name": None}

        sample = LocationSample(
            sample_id="",
            source=self.source_name,
            sampled_at=time.time(),
            lat=fix.lat,
            lng=fix.lng,
            accuracy_m=fix.accuracy_m,
            city=labels.get("city"),
            region=labels.get("region"),
            country=labels.get("country"),
            metadata={"ap_count": fix.ap_count, "poi_name": labels.get("poi_name")},
        )
        sample.sample_id = await self._store.insert(sample)
        logger.info(
            "wifi sample stored",
            city=sample.city, accuracy_m=fix.accuracy_m, ap_count=fix.ap_count,
        )
        return sample
