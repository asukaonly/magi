"""Concrete sample source for MoodAggregateSchedulerContrib.

Queries L2 tom_trait_assertions filtered to mood/valence trait families
within a time window, normalizes each into a (timestamp, valence) pair
clamped to [-1.0, 1.0]. Plan 4 wiring; Plan 2 left this as a Protocol stub.
"""

from __future__ import annotations

from typing import Any, Protocol


class _L2StoreProtocol(Protocol):
    async def list_tom_assertions(self, **kwargs) -> list[dict[str, Any]]: ...


# Trait families that count as valence-bearing for the mood aggregate.
# Keep narrow — Plan 4 ships with just "mood" and "valence"; expansion is a
# tuning decision that lives in this constant.
MOOD_TRAIT_FAMILIES = ["mood", "valence"]


class L2ValenceSampleSource:
    """Concrete sample source backed by L2 tom_trait_assertions."""

    def __init__(self, *, l2_store: _L2StoreProtocol) -> None:
        self._l2_store = l2_store

    async def list_valence_samples(
        self, *, start: float, end: float,
    ) -> list[tuple[float, float]]:
        try:
            assertions = await self._l2_store.list_tom_assertions(
                trait_families=MOOD_TRAIT_FAMILIES,
                temporal_clause=("observed_at >= ? AND observed_at <= ?", [start, end]),
                limit=10000,
            )
        except Exception:
            return []

        samples: list[tuple[float, float]] = []
        for assertion in assertions or []:
            ts = assertion.get("observed_at")
            if ts is None:
                ts = assertion.get("created_at")
            if ts is None:
                continue
            try:
                timestamp = float(ts)
            except (TypeError, ValueError):
                continue

            raw_value = assertion.get("trait_value")
            try:
                valence = float(raw_value)
            except (TypeError, ValueError):
                continue
            valence = max(-1.0, min(1.0, valence))

            samples.append((timestamp, valence))

        return samples
