"""Entity and reconciliation contracts for L2 memory."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


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
class ResolvedEntityMention:
    """Typed resolved entity mention used inside the L2 pipeline."""

    mention_text: str
    normalized_surface: str
    entity_type: str | None
    resolved_entity_id: str | None
    confidence: float | None
    evidence_event_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.mention_text = _non_empty_text(self.mention_text, field_name="mention_text")
        self.normalized_surface = _non_empty_text(
            self.normalized_surface or self.mention_text,
            field_name="normalized_surface",
        )
        self.entity_type = _optional_text(self.entity_type)
        self.resolved_entity_id = _optional_text(self.resolved_entity_id)
        self.confidence = None if self.confidence is None else float(self.confidence)
        self.evidence_event_ids = [
            str(event_id).strip() for event_id in self.evidence_event_ids if str(event_id).strip()
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2FocalEntityRef:
    """Typed entity reference used when loading contradiction context."""

    entity_id: str
    entity_type: str

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2KnowledgeEdgeWrite:
    """Normalized knowledge-edge payload ready for L2 persistence.

    ``valid_from`` / ``valid_to`` describe the temporal validity window of
    the asserted fact (None means "unbounded on that side"); when no
    ``valid_from`` is supplied the persistence layer defaults to
    ``observed_at`` so a freshly-asserted fact is at least valid from the
    moment it was first observed.
    """

    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    evidence_event_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    observed_at: float = 0.0
    source_type: str = "unknown"
    extraction_method: str = "rule"
    valid_from: float | None = None
    valid_to: float | None = None

    def __post_init__(self) -> None:
        self.subject_id = _non_empty_text(self.subject_id, field_name="subject_id")
        self.subject_type = _non_empty_text(self.subject_type, field_name="subject_type")
        self.predicate = _non_empty_text(self.predicate, field_name="predicate")
        self.object_id = _non_empty_text(self.object_id, field_name="object_id")
        self.object_type = _non_empty_text(self.object_type, field_name="object_type")
        self.evidence_event_ids = [
            str(item).strip() for item in self.evidence_event_ids if str(item).strip()
        ]
        self.confidence = float(self.confidence or 0.0)
        self.observed_at = float(self.observed_at or 0.0)
        self.source_type = _optional_text(self.source_type) or "unknown"
        self.extraction_method = _optional_text(self.extraction_method) or "rule"
        self.valid_from = float(self.valid_from) if self.valid_from is not None else None
        self.valid_to = float(self.valid_to) if self.valid_to is not None else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2TomAssertionWrite:
    """Normalized ToM assertion payload ready for L2 persistence."""

    entity_id: str
    entity_type: str
    trait_name: str
    trait_value: str
    confidence_score: float = 0.0
    evidence_events: list[str] = field(default_factory=list)
    volatility_index: float = 0.5
    source_domain: str = ""
    inference_depth: str = ""
    validation_state: str = "tentative"
    first_inferred_at: float = 0.0
    last_validated_at: float = 0.0
    trait_family: str = ""
    target_entity_id: str = ""
    target_entity_type: str = ""
    target_scope: str = "global"
    temporal_scope: str = ""
    decay_policy: str = ""
    decay_anchor_at: float = 0.0
    context_ref_id: str = ""
    expires_at: float | None = None
    memory_subdomain: str = ""

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")
        self.trait_name = _non_empty_text(self.trait_name, field_name="trait_name")
        self.trait_value = str(self.trait_value)
        self.confidence_score = float(self.confidence_score or 0.0)
        self.evidence_events = [
            str(item).strip() for item in self.evidence_events if str(item).strip()
        ]
        self.volatility_index = float(self.volatility_index or 0.5)
        self.source_domain = _optional_text(self.source_domain) or ""
        self.inference_depth = _optional_text(self.inference_depth) or ""
        self.validation_state = _optional_text(self.validation_state) or "tentative"
        self.first_inferred_at = float(self.first_inferred_at or 0.0)
        self.last_validated_at = float(self.last_validated_at or 0.0)
        self.trait_family = _optional_text(self.trait_family) or ""
        self.target_entity_id = _optional_text(self.target_entity_id) or ""
        self.target_entity_type = _optional_text(self.target_entity_type) or ""
        self.target_scope = _optional_text(self.target_scope) or "global"
        self.temporal_scope = _optional_text(self.temporal_scope) or ""
        self.decay_policy = _optional_text(self.decay_policy) or ""
        self.decay_anchor_at = float(self.decay_anchor_at or 0.0)
        self.context_ref_id = _optional_text(self.context_ref_id) or ""
        expires_at_value: Any = self.expires_at
        self.expires_at = None if expires_at_value in (None, "") else float(expires_at_value)
        self.memory_subdomain = _optional_text(self.memory_subdomain) or ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2ExistingRecord:
    """Normalized existing record payload used for contradiction checks."""

    record_id: str
    record_type: str
    entity_id: str = ""
    entity_type: str = ""
    trait_name: str = ""
    trait_value: str = ""
    validation_state: str = ""
    subject_id: str = ""
    predicate: str = ""
    object_id: str = ""
    status: str = ""
    confidence: float = 0.0
    evidence_event_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2ExistingRecord":
        return cls(
            record_id=payload.get("record_id", ""),
            record_type=payload.get("record_type", ""),
            entity_id=payload.get("entity_id", ""),
            entity_type=payload.get("entity_type", ""),
            trait_name=payload.get("trait_name", ""),
            trait_value=payload.get("trait_value", ""),
            validation_state=payload.get("validation_state", ""),
            subject_id=payload.get("subject_id", ""),
            predicate=payload.get("predicate", ""),
            object_id=payload.get("object_id", ""),
            status=payload.get("status", ""),
            confidence=payload.get("confidence", 0.0),
            evidence_event_ids=payload.get("evidence_event_ids", []),
        )

    def __post_init__(self) -> None:
        self.record_id = _non_empty_text(self.record_id, field_name="record_id")
        self.record_type = _non_empty_text(self.record_type, field_name="record_type")
        self.entity_id = _optional_text(self.entity_id) or ""
        self.entity_type = _optional_text(self.entity_type) or ""
        self.trait_name = _optional_text(self.trait_name) or ""
        self.trait_value = _optional_text(self.trait_value) or ""
        self.validation_state = _optional_text(self.validation_state) or ""
        self.subject_id = _optional_text(self.subject_id) or ""
        self.predicate = _optional_text(self.predicate) or ""
        self.object_id = _optional_text(self.object_id) or ""
        self.status = _optional_text(self.status) or ""
        self.confidence = float(self.confidence or 0.0)
        self.evidence_event_ids = [
            str(item).strip() for item in self.evidence_event_ids if str(item).strip()
        ]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2SourceEvent:
    """Normalized evidence event payload used during conflict arbitration."""

    event_id: str
    timestamp: float
    source: str
    event_type: str
    content: str
    author_type: str = "user"
    session_id: str | None = None
    user_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2SourceEvent":
        return cls(
            event_id=payload.get("event_id", ""),
            timestamp=payload.get("timestamp", 0.0),
            source=payload.get("source", "unknown"),
            event_type=payload.get("event_type", ""),
            content=payload.get("content", ""),
            author_type=payload.get("author_type", "user"),
            session_id=payload.get("session_id"),
            user_id=payload.get("user_id"),
        )

    def __post_init__(self) -> None:
        self.event_id = _non_empty_text(self.event_id, field_name="event_id")
        self.timestamp = float(self.timestamp or 0.0)
        self.source = _optional_text(self.source) or "unknown"
        self.event_type = _optional_text(self.event_type) or ""
        self.content = str(self.content or "")
        self.author_type = _optional_text(self.author_type) or "user"
        self.session_id = _optional_text(self.session_id)
        self.user_id = _optional_text(self.user_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityResolution:
    """Normalized entity resolution result returned by the L2 LLM service."""

    decision: str = "unresolved"
    matched_entity_id: str | None = None
    matched_entity_name: str | None = None
    confidence: float = 0.0
    reason_tags: list[str] = field(default_factory=list)
    should_merge: bool = False
    canonical_name_suggestion: str | None = None

    def __post_init__(self) -> None:
        self.decision = _optional_text(self.decision) or "unresolved"
        self.matched_entity_id = _optional_text(self.matched_entity_id)
        self.matched_entity_name = _optional_text(self.matched_entity_name)
        self.confidence = float(self.confidence or 0.0)
        self.reason_tags = [str(item).strip() for item in self.reason_tags if str(item).strip()]
        self.should_merge = bool(self.should_merge)
        self.canonical_name_suggestion = _optional_text(self.canonical_name_suggestion)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityResolutionMention:
    """Typed entity-resolution mention payload."""

    mention_text: str
    entity_type: str | None = None
    context_text: str | None = None

    def __post_init__(self) -> None:
        self.mention_text = _non_empty_text(self.mention_text, field_name="mention_text")
        self.entity_type = _optional_text(self.entity_type)
        self.context_text = _optional_text(self.context_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2EntityCandidate:
    """Typed candidate entity payload used for L2 resolution prompts."""

    entity_id: str
    canonical_name: str
    entity_type: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "L2EntityCandidate":
        return cls(
            entity_id=payload.get("entity_id", ""),
            canonical_name=payload.get("canonical_name", ""),
            entity_type=payload.get("entity_type", ""),
        )

    def __post_init__(self) -> None:
        self.entity_id = _non_empty_text(self.entity_id, field_name="entity_id")
        self.canonical_name = _non_empty_text(self.canonical_name, field_name="canonical_name")
        self.entity_type = _non_empty_text(self.entity_type, field_name="entity_type")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class L2BatchEntityResolutionItem:
    """One mention + its candidates for batch entity resolution."""

    mention_key: str
    mention: L2EntityResolutionMention
    candidate_entities: list[L2EntityCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention_key": self.mention_key,
            "mention": self.mention.to_dict(),
            "candidate_entities": [c.to_dict() for c in self.candidate_entities],
        }


__all__ = [
    "L2BatchEntityResolutionItem",
    "L2EntityCandidate",
    "L2EntityResolution",
    "L2EntityResolutionMention",
    "L2ExistingRecord",
    "L2FocalEntityRef",
    "L2KnowledgeEdgeWrite",
    "L2SourceEvent",
    "L2TomAssertionWrite",
    "ResolvedEntityMention",
]
