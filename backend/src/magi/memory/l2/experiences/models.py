"""Contracts for L2 experience persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ExperienceStatus = Literal["candidate", "active", "hidden", "merged", "invalidated"]
ExperienceMemberType = Literal["episode", "event"]
ExperienceMemberRole = Literal["core", "supporting", "context", "excluded"]


@dataclass(frozen=True)
class ExperienceMemberWrite:
    """A source episode or event membership for an L2 experience."""

    member_type: ExperienceMemberType
    member_id: str
    role: ExperienceMemberRole = "core"
    confidence: float = 0.5


@dataclass(frozen=True)
class ExperienceWrite:
    """Create payload for an L2 experience."""

    experience_id: str
    time_start: float
    time_end: float
    status: ExperienceStatus = "candidate"
    title: str | None = None
    experience_type: str | None = None
    intent: str | None = None
    outcome: str | None = None
    magi_interpretation: str | None = None
    narrative_score: float = 0.0
    primary_entity_ids: list[str] = field(default_factory=list)
    primary_place_ids: list[str] = field(default_factory=list)
    primary_topic_keys: list[str] = field(default_factory=list)
    source_episode_count: int = 0
    source_event_count: int = 0


@dataclass(frozen=True)
class ExperiencePromotionStats:
    """Counters returned by future experience promotion runs."""

    candidates: int = 0
    promoted: int = 0
    skipped_duplicates: int = 0
    rejected: int = 0


__all__ = [
    "ExperienceMemberRole",
    "ExperienceMemberType",
    "ExperienceMemberWrite",
    "ExperiencePromotionStats",
    "ExperienceStatus",
    "ExperienceWrite",
]
