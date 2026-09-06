"""Contracts for the L3 reflection write pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..l2.models import ReconciledTraitOutcome

SummaryType = Literal["temporal", "thematic", "insight"]
SummaryCategory = Literal[
    "hour",
    "day",
    "week",
    "month",
    "quarter",
    "year",
    "topic",
    "episodic",
    "project",
    "goal",
    "person",
    "relationship",
    "constraint",
    "decision",
    "blocker",
    "task_reflection",
    "state_change",
    "trend_shift",
    "conflict_resolution",
    "goal_refinement",
    "preference_emergence",
    "risk_escalation",
    "milestone_review",
]


@dataclass(slots=True)
class TaskOutcomePacket:
    """Normalized task completion facts for downstream L3 reflection."""

    task_id: str
    user_id: str
    task_title: str
    task_status: Literal["completed", "partial", "failed", "cancelled"]
    task_kind: (
        Literal["user_goal_task", "orchestration_task", "system_task", "tool_task"] | None
    ) = None
    user_goal: str | None = None
    evidence_event_ids: list[str] = field(default_factory=list)
    result_summary: str | None = None
    decisions: list[dict[str, object]] = field(default_factory=list)
    constraints: list[dict[str, object]] = field(default_factory=list)
    blockers: list[dict[str, object]] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StateChangePacket:
    """Normalized L2 reconcile outcomes for downstream L3 insights."""

    entity_id: str
    entity_type: str
    outcomes: list[ReconciledTraitOutcome] = field(default_factory=list)
    trigger_reason: str = "l2_reconcile"


@dataclass(slots=True)
class ContradictionPacket:
    """Normalized contradiction outcomes for downstream L3 insights."""

    source_event_ids: list[str] = field(default_factory=list)
    outcomes: list[ReconciledTraitOutcome] = field(default_factory=list)
    trigger_reason: str = "l2_contradiction"


@dataclass(slots=True)
class TrendShiftPacket:
    """Normalized long-span reconcile outcomes for downstream L3 insights."""

    entity_id: str
    entity_type: str
    outcomes: list[ReconciledTraitOutcome] = field(default_factory=list)
    trigger_reason: str = "l2_reconcile"


@dataclass(slots=True)
class L3Candidate:
    """Structured candidate before validation and persistence."""

    content: str
    source_event_ids: list[str]
    summary_category: SummaryCategory
    summary_type: SummaryType | None = None
    subtypes: list[str] = field(default_factory=list)
    insight_key: str | None = None
    review_state: str | None = None
    insight_metadata: dict[str, object] = field(default_factory=dict)
    claim_dependencies: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.summary_type is None:
            self.summary_type = (
                "insight" if self.summary_category == "task_reflection" else "temporal"
            )


@dataclass(slots=True)
class ValidationDecision:
    """Result of evaluating an L3 candidate for persistence."""

    action: Literal["reject", "route_to_l4", "merge_existing", "accept"]
    reason: str


@dataclass(slots=True)
class TemporalEvidenceItem:
    """Compact temporal-summary evidence item derived from an L1 event."""

    event_id: str
    event_type: str
    content: str
    timestamp: float | None = None
    memory_domain: str | None = None
    importance_score: float | None = None
    interpretation_context: dict[str, str] | None = None


@dataclass(slots=True)
class TemporalEvidencePack:
    """Compact prompt payload for temporal L3 summarization."""

    summary_category: SummaryCategory
    period_start: float
    period_end: float
    source_event_count: int
    window_event_count: int | None = None
    omitted_event_count: int = 0
    source_event_ids: list[str] = field(default_factory=list)
    events: list[TemporalEvidenceItem] = field(default_factory=list)
    importance_aggregate: float | None = None
    event_type_distribution: dict[str, int] = field(default_factory=dict)
    rule_hints: dict[str, object] = field(default_factory=dict)
    plugin_summary_features: dict[str, object] = field(default_factory=dict)
    source_distribution: dict[str, object] = field(default_factory=dict)
    selection_policy: dict[str, object] = field(default_factory=dict)
    dependency_event_ids: list[str] = field(default_factory=list)
    dependency_summary_ids: list[str] = field(default_factory=list)
    previous_period_summaries: list[dict[str, object]] = field(default_factory=list)
    child_period_summaries: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class TemporalSummaryLLMOutput:
    """Structured LLM output for temporal summary rewriting."""

    content: str
    essence_prose: str | None = None
    key_topics: list[str] = field(default_factory=list)
    key_entities: list[dict[str, object]] = field(default_factory=list)
    sentiment_summary: dict[str, object] | None = None
    change_and_pattern: dict[str, object] | None = None
    importance_aggregate: float | None = None


@dataclass(slots=True)
class TemporalGenerationResult:
    """Outcome of temporal summary generation with fallback awareness."""

    candidate: L3Candidate
    summary_overrides: dict[str, object] = field(default_factory=dict)
    used_fallback: bool = False


@dataclass(slots=True)
class ThematicEvidenceItem:
    """Compact thematic-summary evidence item derived from an L1 event."""

    event_id: str
    event_type: str
    content: str
    timestamp: float | None = None
    importance_score: float | None = None
    interpretation_context: dict[str, str] | None = None


@dataclass(slots=True)
class ThematicEvidencePack:
    """Compact prompt payload for thematic topic summarization."""

    topic: str
    source_event_count: int
    source_event_ids: list[str] = field(default_factory=list)
    events: list[ThematicEvidenceItem] = field(default_factory=list)
    importance_aggregate: float | None = None
    event_type_distribution: dict[str, int] = field(default_factory=dict)
    rule_hints: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ThematicSummaryLLMOutput:
    """Structured LLM output for thematic summary rewriting."""

    content: str
    key_topics: list[str] = field(default_factory=list)
    key_entities: list[dict[str, object]] = field(default_factory=list)
    importance_aggregate: float | None = None


@dataclass(slots=True)
class ThematicGenerationResult:
    """Outcome of thematic summary generation with fallback awareness."""

    candidate: L3Candidate
    summary_overrides: dict[str, object] = field(default_factory=dict)
    used_fallback: bool = False


@dataclass(slots=True)
class EpisodicEvidenceItem:
    """Verbatim event kept in the prompt because it carries high signal."""

    event_id: str
    event_type: str
    content: str
    timestamp: float | None = None
    importance_score: float | None = None
    source: str | None = None  # raw L1 source name, e.g. "chat_projector"
    role: str | None = None  # "user" / "assistant" / None — for chat events


@dataclass(slots=True)
class EpisodicEvidencePack:
    """Compact prompt payload for episode-bounded summarization."""

    episode_id: str
    episode_type: str
    time_start: float
    time_end: float
    primary_entity_ids: list[str] = field(default_factory=list)
    primary_topic_keys: list[str] = field(default_factory=list)
    source_event_count: int = 0
    source_event_ids: list[str] = field(default_factory=list)
    events: list[EpisodicEvidenceItem] = field(default_factory=list)
    folded_groups: list[str] = field(default_factory=list)
    derived_topics: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EpisodicSummaryLLMOutput:
    """Structured LLM output for episodic summary."""

    label: str
    content: str
    key_topics: list[str] = field(default_factory=list)
    key_entities: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class ExperienceReviewLLMOutput:
    """Structured LLM output for experience review."""

    label: str
    narrative: str
    intent: str = ""
    outcome: str = ""
    key_topics: list[str] = field(default_factory=list)
    key_entities: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class EpisodicGenerationResult:
    """Outcome of episodic summary generation with fallback awareness."""

    candidate: L3Candidate
    summary_overrides: dict[str, object] = field(default_factory=dict)
    used_fallback: bool = False
