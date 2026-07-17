"""Concrete sample source for MoodAggregateSchedulerContrib.

Queries L2 tom_trait_assertions filtered to mood/valence trait families
within a time window, and retains the exact source events for each normalized
valence sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _L2StoreProtocol(Protocol):
    async def list_tom_assertions(self, **kwargs) -> list[dict[str, Any]]: ...


# Keep the valence-bearing family set narrow; expansion is a tuning decision.
MOOD_TRAIT_FAMILIES = ["mood", "valence"]


@dataclass(frozen=True, slots=True)
class ValenceSample:
    """One mood sample plus the source events that make it deletable."""

    timestamp: float
    valence: float
    source_event_ids: tuple[str, ...]


class L2ValenceSampleSource:
    """Concrete sample source backed by L2 tom_trait_assertions."""

    def __init__(self, *, l2_store: _L2StoreProtocol) -> None:
        self._l2_store = l2_store

    async def list_valence_samples(
        self,
        *,
        start: float,
        end: float,
    ) -> list[ValenceSample]:
        try:
            assertions = await self._l2_store.list_tom_assertions(
                trait_families=MOOD_TRAIT_FAMILIES,
                temporal_clause=("observed_at >= ? AND observed_at <= ?", [start, end]),
                limit=10000,
            )
        except Exception:
            return []

        samples: list[ValenceSample] = []
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

            raw_source_event_ids = assertion.get("evidence_events")
            if not isinstance(raw_source_event_ids, (list, tuple, set)):
                continue
            source_event_ids = tuple(
                dict.fromkeys(
                    str(event_id).strip()
                    for event_id in raw_source_event_ids
                    if str(event_id).strip()
                )
            )
            if not source_event_ids:
                continue

            samples.append(
                ValenceSample(
                    timestamp=timestamp,
                    valence=valence,
                    source_event_ids=source_event_ids,
                )
            )

        return samples


__all__ = ["L2ValenceSampleSource", "MOOD_TRAIT_FAMILIES", "ValenceSample"]
