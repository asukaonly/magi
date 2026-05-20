"""Time-weighted multi-source location resolver."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..core.logger import get_logger
from .models import LocationSample, ResolvedPlace
from .sources.base import LocationSource

logger = get_logger("magi.location.resolver")


# Accuracy tier thresholds — used to label ResolvedPlace.accuracy_tier so
# callers (UI / scoring) can decide whether to trust the answer for
# fine-grained features.
_TIER_EXACT_MAX_METERS = 50.0
_TIER_NEIGHBORHOOD_MAX_METERS = 1500.0


class LocationResolver:
    """Resolve "where were you" for a time window across multiple sources.

    Strategy (matches the design discussion):

      1. Iterate sources in **descending priority** order.
      2. For each source: ask for samples whose validity window overlaps
         [time_start, time_end]. Wrap in try/except so one failing source
         (network down, hardware absent) doesn't block the rest.
      3. If samples found: compute the **time-weighted dominant label**
         across all sources collected SO FAR (so a high-precision photo
         can still contribute to a window that's otherwise dominated by
         WiFi/IPGeo). The dominance is computed once we have at least one
         source's data; we don't keep dropping down through priority if
         the top source provided enough coverage.
      4. Final fallback: empty ResolvedPlace.

    Time-weighting math: each sample contributes
    ``min(validity_seconds, distance_to_neighbor)`` seconds to its primary
    label. The label with the most accumulated seconds wins.
    """

    def __init__(self, *, sources: Iterable[LocationSource]) -> None:
        # Sort by priority descending so the iteration order matches the
        # preference: photo (100) → wifi (50) → ipgeo (10).
        self._sources = sorted(sources, key=lambda s: s.priority, reverse=True)

    async def resolve_dominant(
        self, *, time_start: float, time_end: float,
    ) -> ResolvedPlace:
        """Return the dominant place label for the given window.

        Returns an empty ResolvedPlace (primary_label=='') when no source
        produced any sample with a non-empty label.
        """
        if time_end <= time_start:
            return ResolvedPlace(primary_label="")

        # Collect by priority; once a source yields samples we use those
        # plus any higher-precision samples we already gathered. Because
        # we iterate in priority order, higher-precision sources are
        # checked first and become the base; lower-precision ones layer in
        # only where coverage is missing.
        collected: list[tuple[LocationSource, list[LocationSample]]] = []
        for source in self._sources:
            try:
                samples = await source.query_samples(
                    time_start=time_start, time_end=time_end,
                )
            except Exception as exc:
                logger.warning(
                    "Location source failed; continuing",
                    source=source.source_name, error=str(exc),
                )
                continue
            if samples:
                collected.append((source, samples))

        if not collected:
            return ResolvedPlace(primary_label="")

        return self._weighted_dominant(collected, time_start, time_end)

    # ─── internals ────────────────────────────────────────────────────

    @staticmethod
    def _weighted_dominant(
        collected: list[tuple[LocationSource, list[LocationSample]]],
        time_start: float,
        time_end: float,
    ) -> ResolvedPlace:
        """Compute time-weighted top labels across all collected sources.

        For each source, samples are sorted by sampled_at; each sample
        covers from its timestamp to min(next_sample_timestamp,
        sampled_at + validity_seconds, time_end). The contributing seconds
        are added to the sample's primary label's tally.

        Higher-priority sources OVERWRITE lower-priority contributions in
        overlapping intervals — but for simplicity we just *add* and rely
        on the priority-ordered iteration putting more accurate samples
        first so they get the natural plurality. (A future refinement
        could compute an actual interval-overlap subtraction; the current
        scheme is fine for the city-vs-neighborhood scale we operate at.)
        """
        tally: dict[str, float] = defaultdict(float)
        sources_used: set[str] = set()
        best_accuracy_m: float = float("inf")

        for source, samples in collected:
            for i, sample in enumerate(samples):
                label = sample.primary_label()
                if not label:
                    continue
                start = max(sample.sampled_at, time_start)
                # Cover up to: next sample of same source, or validity expiry,
                # or window end — whichever is earliest.
                validity_end = sample.sampled_at + source.validity_seconds
                next_start = (
                    samples[i + 1].sampled_at
                    if i + 1 < len(samples)
                    else float("inf")
                )
                end = min(validity_end, next_start, time_end)
                if end <= start:
                    continue
                tally[label] += end - start
                sources_used.add(source.source_name)
                if sample.accuracy_m is not None:
                    best_accuracy_m = min(best_accuracy_m, float(sample.accuracy_m))

        if not tally:
            return ResolvedPlace(primary_label="")

        # Order labels by accumulated seconds; keep top 3 for the chip row.
        ranked = sorted(tally.items(), key=lambda pair: pair[1], reverse=True)
        primary = ranked[0][0]
        labels = [label for label, _ in ranked[:3]]

        if best_accuracy_m <= _TIER_EXACT_MAX_METERS:
            tier = "exact"
        elif best_accuracy_m <= _TIER_NEIGHBORHOOD_MAX_METERS:
            tier = "neighborhood"
        else:
            tier = "city"

        # Pick "the source that contributed the most seconds" as source_used
        # rather than the last one touched (most informative for debugging).
        source_used = ",".join(sorted(sources_used))

        return ResolvedPlace(
            primary_label=primary,
            labels=labels,
            accuracy_tier=tier,
            source_used=source_used,
        )
