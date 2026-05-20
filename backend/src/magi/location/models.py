"""Data shapes for the location pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(slots=True)
class LocationSample:
    """A single positional observation from one source.

    ``source`` is a short stable string ("ipgeo", "wifi", "photo") used both
    as the storage discriminator and as a key for the resolver's
    source-priority map.

    The reverse-geocoded labels (city/region/country) are stored alongside
    lat/lng so the resolver doesn't need to network-hit on read — the
    capture-time geocode is good enough and we cache it via
    ``PlaceGeocodeCache`` to dedupe across samples in the same grid cell.
    """

    sample_id: str
    source: str
    sampled_at: float
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy_m: Optional[float] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def primary_label(self) -> str:
        """Most-specific human label available, or empty string."""
        for candidate in (self.city, self.region, self.country):
            if candidate and candidate.strip():
                return candidate.strip()
        return ""


@dataclass(slots=True)
class ResolvedPlace:
    """The resolver's answer for a time window.

    ``primary_label`` is the dominant location chunk (e.g. "杭州"); the
    weighted breakdown is exposed via ``labels`` so callers can render
    secondary chips ("杭州 · 西湖") when meaningful.
    """

    primary_label: str
    labels: list[str] = field(default_factory=list)
    accuracy_tier: str = "city"  # "exact" | "neighborhood" | "city"
    source_used: str = ""  # name of the source the answer came from
