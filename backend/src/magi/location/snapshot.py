"""Read existing host location observations without polling or inferring user presence."""

from __future__ import annotations

import time
from typing import Any

from .sources.ipgeo import IPGEO_VALIDITY_SECONDS
from .sources.wifi import WIFI_VALIDITY_SECONDS
from .store import LocationSampleStore


async def read_host_location(store: LocationSampleStore) -> dict[str, Any]:
    """Keep each observation's own provenance and expiry; do not merge confidence."""
    now = time.time()
    observations: list[dict[str, Any]] = []
    for source, validity in (("wifi", WIFI_VALIDITY_SECONDS), ("ipgeo", IPGEO_VALIDITY_SECONDS)):
        sample = await store.latest(source=source, before=now)
        if sample is None or not sample.primary_label():
            continue
        expires_at = sample.sampled_at + validity
        observations.append(
            {
                "source": source,
                "city": sample.city,
                "region": sample.region,
                "country": sample.country,
                "sampled_at": sample.sampled_at,
                "expires_at": expires_at,
                "freshness": "fresh" if now < expires_at else "stale",
                "precision": "city_estimate" if source == "ipgeo" else "wifi_estimate",
                "accuracy_m": sample.accuracy_m if source == "wifi" else None,
            }
        )
    return {
        "status": "last_known" if observations else "unknown",
        "subject": "service_host",
        "observations": observations,
        "user_location": "unknown",
        "note": (
            "These are stored observations of the service host. They do not establish the user's "
            "current location. IP geolocation may reflect a VPN or network exit. No live lookup was performed."
        ),
    }
