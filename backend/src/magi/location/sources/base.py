"""Protocol shared by all location source backends."""

from __future__ import annotations

from typing import Protocol

from ..models import LocationSample


class LocationSource(Protocol):
    """Source-of-truth-for-position adapter.

    A LocationSource owns a single ingestion strategy (photo EXIF, WiFi
    scan, IP geo lookup, …). The resolver asks each source — in priority
    order — for samples whose validity intersects a time window.

    Implementations are responsible for their own persistence side-effects
    (typically driven by a scheduler) and for surfacing already-cached
    samples on read.
    """

    #: Short stable identifier used both as the storage discriminator
    #: ("photo", "wifi", "ipgeo") and as a key in the resolver registry.
    source_name: str

    #: Higher = preferred. The resolver iterates sources by descending
    #: priority. Conventional values: photo=100, wifi=50, ipgeo=10.
    priority: int

    #: How long a sample remains "valid" past its sampled_at. The resolver
    #: uses this to compute time-weighted contributions when aggregating.
    validity_seconds: int

    async def query_samples(
        self, *, time_start: float, time_end: float,
    ) -> list[LocationSample]:
        """Return samples whose validity window overlaps [start, end].

        Implementations should return them sorted chronologically by
        ``sampled_at`` so the resolver's weighted aggregation reads in
        natural order.
        """
        ...
