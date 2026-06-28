"""Shared contracts for L2 experience seed discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence


RepeatedGoalSelector = Callable[
    [Sequence[dict[str, Any]]],
    Sequence[Mapping[str, Any]] | Awaitable[Sequence[Mapping[str, Any]]],
]


@dataclass(frozen=True)
class ExperienceSeedDiscoveryStats:
    """Counters returned by experience seed discovery runs."""

    candidates: int = 0
    created: int = 0
    skipped_duplicates: int = 0
    skipped_generic: int = 0
    created_seed_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _EpisodeSeedFeatures:
    """Normalized signal packet used by deterministic repeated-goal discovery."""

    episode: dict[str, Any]
    text: str
    entity_ids: list[str]
    place_ids: list[str]
    topic_keys: list[str]
    text_tokens: list[str]
