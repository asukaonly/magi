"""Bounded, storage-neutral event overview reads."""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True, slots=True)
class EventOverviewQuery:
    boundaries: tuple[float, ...]
    retrieval_scopes: tuple[str, ...]
    term_groups: tuple[tuple[str, ...], ...] = ()
    previews_per_bucket: int = 3

    def __post_init__(self) -> None:
        if not 2 <= len(self.boundaries) <= 33:
            raise ValueError("Event overviews require between 1 and 32 buckets")
        if any(not math.isfinite(value) for value in self.boundaries):
            raise ValueError("Event overview boundaries must be finite")
        if any(a >= b for a, b in zip(self.boundaries, self.boundaries[1:])):
            raise ValueError("Event overview boundaries must be increasing")
        if not 0 <= self.previews_per_bucket <= 3:
            raise ValueError("Event overviews allow at most three previews per bucket")


@dataclass(frozen=True, slots=True)
class EventOverviewCount:
    bucket: int
    source: str
    count: int


@dataclass(frozen=True, slots=True)
class EventOverviewPreview:
    bucket: int
    event_id: str
    timestamp: float
    source: str
    title: str
    summary: str


@dataclass(frozen=True, slots=True)
class EventOverview:
    counts: list[EventOverviewCount] = field(default_factory=list)
    previews: list[EventOverviewPreview] = field(default_factory=list)
