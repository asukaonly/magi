"""Contracts for L2 experience persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ExperienceStatus = Literal["candidate", "active", "hidden", "merged", "invalidated"]
ExperienceMemberType = Literal["episode", "event"]
ExperienceMemberRole = Literal["core", "supporting", "context", "excluded"]
ExperienceSeedType = Literal["manual", "project", "repeated_goal"]
ExperienceSeedStatus = Literal["candidate", "accepted", "rejected", "promoted", "stale"]
ExperienceSeedEvidenceRefType = Literal["episode", "event", "entity", "summary"]
ExperienceSeedEvidenceRole = Literal[
    "trigger",
    "support",
    "candidate",
    "included",
    "excluded",
    "boundary",
]


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
    source_seed_id: str | None = None


@dataclass(frozen=True)
class ExperienceSeedWrite:
    """Create payload for an L2 experience seed."""

    seed_id: str
    seed_type: ExperienceSeedType
    status: ExperienceSeedStatus = "candidate"
    title: str | None = None
    description: str | None = None
    anchor_entity_ids: list[str] = field(default_factory=list)
    anchor_place_ids: list[str] = field(default_factory=list)
    anchor_topic_keys: list[str] = field(default_factory=list)
    time_start: float | None = None
    time_end: float | None = None
    confidence: float = 0.0
    created_by: str = "system"
    source_ref_type: str | None = None
    source_ref_id: str | None = None


@dataclass(frozen=True)
class ExperienceSeedEvidenceWrite:
    """Evidence reference linked to an L2 experience seed."""

    ref_type: ExperienceSeedEvidenceRefType
    ref_id: str
    role: ExperienceSeedEvidenceRole = "support"
    confidence: float = 0.5
    reason: str | None = None


@dataclass(frozen=True)
class ExperiencePromotionStats:
    """Counters returned by future experience promotion runs."""

    candidates: int = 0
    promoted: int = 0
    skipped_duplicates: int = 0
    rejected: int = 0
    deferred: int = 0
    promoted_experience_ids: list[str] = field(default_factory=list)


__all__ = [
    "ExperienceMemberRole",
    "ExperienceMemberType",
    "ExperienceMemberWrite",
    "ExperiencePromotionStats",
    "ExperienceSeedEvidenceRefType",
    "ExperienceSeedEvidenceRole",
    "ExperienceSeedEvidenceWrite",
    "ExperienceSeedStatus",
    "ExperienceSeedType",
    "ExperienceSeedWrite",
    "ExperienceStatus",
    "ExperienceWrite",
]
