"""Episode-related contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


def _non_empty_text(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(slots=True)
class EpisodeWrite:
    """Payload for creating or extending an episode."""

    episode_id: str
    episode_type: str = "activity"
    status: str = "candidate"
    time_start: float = 0.0
    time_end: float = 0.0
    parent_episode_id: str = ""
    label: str = ""
    summary: str = ""
    dominant_mode: str = ""
    primary_entity_ids: list[str] = field(default_factory=list)
    primary_place_ids: list[str] = field(default_factory=list)
    primary_topic_keys: list[str] = field(default_factory=list)
    continuity_signals: list[str] = field(default_factory=list)
    formation_method: str = "time_gap_cluster"
    confidence: float = 0.5
    source_event_count: int = 0
    privacy_scope: str = "private"

    # Immersive timeline fields (Plan 1 — Plan 2 fills via LLM/scheduler)
    slice_narrative: str = ""
    slice_sensory_detail: str = ""
    magi_standout: bool = False
    standout_score: float = 0.0
    standout_reason: str = ""
    representative_asset_ref: str = ""

    def __post_init__(self) -> None:
        self.episode_id = _non_empty_text(self.episode_id, field_name="episode_id")
        self.episode_type = _optional_text(self.episode_type) or "activity"
        self.status = _optional_text(self.status) or "candidate"
        self.time_start = float(self.time_start or 0.0)
        self.time_end = float(self.time_end or 0.0)
        self.parent_episode_id = _optional_text(self.parent_episode_id) or ""
        self.label = _optional_text(self.label) or ""
        self.summary = _optional_text(self.summary) or ""
        self.dominant_mode = _optional_text(self.dominant_mode) or ""
        self.primary_entity_ids = [
            str(i).strip() for i in self.primary_entity_ids if str(i).strip()
        ]
        self.primary_place_ids = [str(i).strip() for i in self.primary_place_ids if str(i).strip()]
        self.primary_topic_keys = [
            str(k).strip() for k in self.primary_topic_keys if str(k).strip()
        ]
        self.continuity_signals = [
            str(s).strip() for s in self.continuity_signals if str(s).strip()
        ]
        self.formation_method = _optional_text(self.formation_method) or "time_gap_cluster"
        self.confidence = float(self.confidence or 0.5)
        self.source_event_count = int(self.source_event_count or 0)
        self.privacy_scope = _optional_text(self.privacy_scope) or "private"
        self.slice_narrative = _optional_text(self.slice_narrative) or ""
        self.slice_sensory_detail = _optional_text(self.slice_sensory_detail) or ""
        self.magi_standout = bool(self.magi_standout)
        self.standout_score = float(self.standout_score or 0.0)
        self.standout_reason = _optional_text(self.standout_reason) or ""
        self.representative_asset_ref = _optional_text(self.representative_asset_ref) or ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EpisodeWrite":
        return cls(
            episode_id=str(data.get("episode_id", "")),
            episode_type=str(data.get("episode_type", "activity")),
            status=str(data.get("status", "candidate")),
            time_start=float(data.get("time_start", 0.0)),
            time_end=float(data.get("time_end", 0.0)),
            parent_episode_id=str(data.get("parent_episode_id", "")),
            label=str(data.get("label", "")),
            summary=str(data.get("summary", "")),
            dominant_mode=str(data.get("dominant_mode", "")),
            primary_entity_ids=list(data.get("primary_entity_ids", [])),
            primary_place_ids=list(data.get("primary_place_ids", [])),
            primary_topic_keys=list(data.get("primary_topic_keys", [])),
            continuity_signals=list(data.get("continuity_signals", [])),
            formation_method=str(data.get("formation_method", "time_gap_cluster")),
            confidence=float(data.get("confidence", 0.5)),
            source_event_count=int(data.get("source_event_count", 0)),
            privacy_scope=str(data.get("privacy_scope", "private")),
            slice_narrative=str(data.get("slice_narrative", "") or ""),
            slice_sensory_detail=str(data.get("slice_sensory_detail", "") or ""),
            magi_standout=bool(data.get("magi_standout", False)),
            standout_score=float(data.get("standout_score") or 0.0),
            standout_reason=str(data.get("standout_reason", "") or ""),
            representative_asset_ref=str(data.get("representative_asset_ref", "") or ""),
        )


@dataclass(slots=True)
class EpisodeCandidateJob:
    """Job unit for streaming episode candidate formation."""

    event_id: str
    event_timestamp: float
    event_tags: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    place_ids: list[str] = field(default_factory=list)
    topic_keys: list[str] = field(default_factory=list)
    episode_type_hint: str = "activity"

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.event_timestamp = float(self.event_timestamp or 0.0)
        self.event_tags = [str(t).strip() for t in self.event_tags if str(t).strip()]
        self.entity_ids = [str(i).strip() for i in self.entity_ids if str(i).strip()]
        self.place_ids = [str(i).strip() for i in self.place_ids if str(i).strip()]
        self.topic_keys = [str(k).strip() for k in self.topic_keys if str(k).strip()]
        self.episode_type_hint = _optional_text(self.episode_type_hint) or "activity"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EpisodeCandidateJob":
        return cls(
            event_id=str(data.get("event_id", "")),
            event_timestamp=float(data.get("event_timestamp", 0.0)),
            event_tags=list(data.get("event_tags", [])),
            entity_ids=list(data.get("entity_ids", [])),
            place_ids=list(data.get("place_ids", [])),
            topic_keys=list(data.get("topic_keys", [])),
            episode_type_hint=str(data.get("episode_type_hint", "activity")),
        )


@dataclass(slots=True)
class EpisodeConsolidationStats:
    """Statistics for a single episode consolidation run."""

    promoted: int = 0
    standouts: int = 0
    merged: int = 0
    invalidated: int = 0
    summaries_generated: int = 0
    embeddings_queued: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "EpisodeCandidateJob",
    "EpisodeConsolidationStats",
    "EpisodeWrite",
]
