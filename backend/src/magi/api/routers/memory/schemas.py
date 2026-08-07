"""Pydantic schemas for memory API routes."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RetrievalRequest(BaseModel):
    query: str = Field(..., description="Search text")
    query_mode: Optional[str] = Field(
        default=None,
        description=(
            "Optional retrieval mode. Omit for auto routing; supported values include "
            "event_stream, exact_fact, current_state, episode_recall, experience_recall, "
            "summary, strategy, "
            "plus legacy detail|experience|graph."
        ),
    )
    time_range: Dict[str, Any] = Field(default_factory=dict)
    source_filters: List[str] = Field(default_factory=list)
    domain_filters: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=200)


class ProcedureResponse(BaseModel):
    skill_id: str
    skill_name: str
    skill_category: str
    success_rate: float
    total_attempts: int
    circuit_breaker_state: str


class ManualL2EventBody(BaseModel):
    text: str = Field(..., description="Manual event text")
    user_id: str = Field(..., description="User id for the synthetic event")
    session_id: Optional[str] = Field(default=None, description="Optional session id")
    source: str = Field(default="l2_lab", description="Synthetic event source label")
    entity_focus_hint: Optional[str] = Field(default=None, description="Optional focus entity id")


class EvalReplayRecordBody(BaseModel):
    namespace: str = Field(..., description="Benchmark namespace")
    session_id: str = Field(..., description="Replay session id")
    timestamp: float = Field(..., description="Replay timestamp")
    role: str = Field(..., description="Replay speaker role")
    content: str = Field(..., description="Replay text content")
    turn_id: Optional[str] = Field(default=None, description="Optional replay turn id")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional replay metadata")


class EvalReplayRequest(BaseModel):
    namespace: str = Field(..., description="Benchmark namespace")
    records: List[EvalReplayRecordBody] = Field(default_factory=list, description="Replay records")


class EvalQueryRequest(BaseModel):
    namespace: str = Field(..., description="Benchmark namespace")
    query: str = Field(..., description="Benchmark memory query")
    query_timestamp: Optional[float] = Field(default=None, description="Optional query timestamp")
    top_k: int = Field(default=10, ge=1, le=200, description="Top-k retrieval limit")
    mode: str = Field(
        default="auto", description="Retrieval mode hint, including l1_only for debug-only L1 reads"
    )
    answer_with_llm: bool = Field(
        default=False, description="Whether to synthesize a final answer with the runtime LLM"
    )
    show_prompt: bool = Field(
        default=False, description="Whether to include the synthesized LLM prompt in debug output"
    )


class EvalJudgeAnswerRequest(BaseModel):
    system_prompt: str = Field(..., min_length=1, description="Judge system prompt")
    prompt: str = Field(..., min_length=1, description="Judge user prompt")
    max_tokens: int = Field(default=512, ge=1, le=4096, description="Maximum judge output tokens")
    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="Judge sampling temperature"
    )
    timeout_seconds: Optional[float] = Field(
        default=120.0, ge=1.0, le=600.0, description="Judge request timeout"
    )


class EvalFinalizeReplayRequest(BaseModel):
    period_types: List[str] = Field(
        default_factory=lambda: ["hour", "day", "week", "month"],
        description="Temporal summary categories to generate after replay",
    )
    generate_summaries: bool = Field(
        default=True,
        description="Whether to generate temporal L3 summaries.",
    )
    flush_l2_projection_jobs: bool = Field(
        default=True,
        description="Whether to claim pending durable L2 projection jobs.",
    )
    drain_l2_edge_embeddings: bool = Field(
        default=True,
        description="Whether to synchronously drain pending L2 edge embeddings.",
    )


class L2EntityActionBody(BaseModel):
    entity_ids: List[str] = Field(..., description="Canonical entity ids")


class GraphConflictRuleBody(BaseModel):
    opposite_predicates: List[str] = Field(
        default_factory=list, description="Predicates that conflict as logical opposites"
    )
    opposite_resolution: Literal["mark_deprecated", "mark_conflicted"] = Field(
        default="mark_deprecated", description="mark_deprecated|mark_conflicted"
    )
    exclusive_group: Optional[str] = Field(
        default=None, description="Optional mutual-exclusion group"
    )
    exclusive_scope: Literal["same_subject"] = Field(
        default="same_subject", description="Conflict scope"
    )
    exclusive_resolution: Literal["mark_deprecated", "mark_conflicted"] = Field(
        default="mark_deprecated", description="mark_deprecated|mark_conflicted"
    )

    @field_validator("opposite_predicates", mode="before")
    @classmethod
    def _normalize_opposites(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("opposite_predicates must be a list of strings")
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("exclusive_group", mode="before")
    @classmethod
    def _normalize_exclusive_group(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class AssertionFeedbackRequest(BaseModel):
    feedback: Literal["confirmed"]


class MemoryCorrectionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["assertion", "edge"]
    id: str = Field(..., min_length=1, max_length=200)


class MemoryContextCondition(BaseModel):
    """One stable condition in a correction context scope."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["project"]
    context_id: str = Field(
        ...,
        pattern=r"^ctx_project_[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def _context_id_matches_dimension(self) -> "MemoryContextCondition":
        if not self.context_id.startswith(f"ctx_{self.dimension}_"):
            raise ValueError("context_id does not match dimension")
        return self


class MemoryContextScope(BaseModel):
    """Stable conjunction of context identities."""

    model_config = ConfigDict(extra="forbid")

    all_of: List[MemoryContextCondition] = Field(..., min_length=1, max_length=1)

    @field_validator("all_of")
    @classmethod
    def _one_condition_per_dimension(
        cls,
        value: List[MemoryContextCondition],
    ) -> List[MemoryContextCondition]:
        dimensions = [item.dimension for item in value]
        if len(set(dimensions)) != len(dimensions):
            raise ValueError("scope contains duplicate dimensions")
        return value


class MemoryStoredContextCondition(BaseModel):
    """A stable condition returned from persisted memory history."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["project", "activity", "place", "person", "time"]
    context_id: str = Field(
        ...,
        pattern=r"^ctx_(project|activity|place|person|time)_[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def _context_id_matches_dimension(self) -> "MemoryStoredContextCondition":
        if not self.context_id.startswith(f"ctx_{self.dimension}_"):
            raise ValueError("context_id does not match dimension")
        return self


class MemoryStoredContextScope(BaseModel):
    """Stable scope returned from persisted memory history."""

    model_config = ConfigDict(extra="forbid")

    all_of: List[MemoryStoredContextCondition] = Field(
        ...,
        min_length=1,
        max_length=5,
    )


class MemoryCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, max_length=200)
    target: MemoryCorrectionTarget
    correction_kind: Literal["record_error", "situation_changed", "scope_refinement"]
    replacement: Optional[Dict[str, Any]] = None
    reason: Optional[str] = Field(default=None, max_length=2000)
    effective_at: Optional[float] = None
    scope: Optional[MemoryContextScope] = None
    source_event_id: Optional[str] = Field(default=None, max_length=200)
    expected_updated_at: Optional[float] = None

    @field_validator("replacement")
    @classmethod
    def _limit_replacement(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) > 8000:
            raise ValueError("replacement is too large")
        replacement_value = value.get("value")
        if replacement_value is not None and len(str(replacement_value)) > 2000:
            raise ValueError("replacement value is too long")
        for key in ("subject_id", "subject_type", "predicate", "object_id", "object_type"):
            if key in value and len(str(value[key])) > 200:
                raise ValueError(f"replacement {key} is too long")
        return value

    @field_validator("effective_at", "expected_updated_at")
    @classmethod
    def _require_finite_timestamp(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("timestamp must be a positive finite number")
        return value


class MemoryCorrectionRevertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, max_length=200)


class MemoryCorrectionClaimValue(BaseModel):
    """Public semantic content of one assertion or relationship claim."""

    model_config = ConfigDict(extra="forbid")

    value: Optional[Any] = None
    trait_value: Optional[Any] = None
    subject_id: Optional[str] = None
    subject_type: Optional[str] = None
    predicate: Optional[str] = None
    object_id: Optional[str] = None
    object_type: Optional[str] = None
    fact_kind: Optional[str] = None
    status: Optional[str] = None
    validation_state: Optional[str] = None
    scope: Optional[MemoryStoredContextScope] = None


class MemoryCorrectionRecord(BaseModel):
    """Public correction history without governance or evidence identifiers."""

    model_config = ConfigDict(extra="forbid")

    correction_id: str
    correction_kind: Literal["record_error", "situation_changed", "scope_refinement"]
    before: Optional[MemoryCorrectionClaimValue] = None
    created_at: float
    state: Literal["active", "reverted"]
    reason: Optional[str] = None
    replacement: Optional[MemoryCorrectionClaimValue] = None
    effective_at: Optional[float] = None
    scope: Optional[MemoryStoredContextScope] = None
    transition_applied_at: Optional[float] = None
    transition_cancelled_at: Optional[float] = None
    target_forgotten: bool = False
    forget_affected: bool = False
    content_redacted: bool = False
    revert_blocked_reason: Optional[Literal["identity_merge", "lineage_collision"]] = None
    resolution_reason: Optional[Literal["identity_merge_noop"]] = None
    can_revert: bool = False


class MemoryCorrectionCommandResponse(BaseModel):
    correction: MemoryCorrectionRecord
    current_claim: Optional[MemoryCorrectionClaimValue] = None
    subject_revision: Optional[int] = None
    derivation_state: Literal["pending", "running", "completed", "failed"]
    created: bool


class MemoryCorrectionVersion(BaseModel):
    """Public, content-only projection of one correction history version."""

    model_config = ConfigDict(extra="forbid")

    trait_value: Optional[Any] = None
    subject_id: Optional[str] = None
    subject_type: Optional[str] = None
    predicate: Optional[str] = None
    object_id: Optional[str] = None
    object_type: Optional[str] = None
    status: Optional[str] = None
    validation_state: Optional[str] = None
    valid_from: Optional[float] = None
    valid_to: Optional[float] = None
    first_inferred_at: Optional[float] = None
    first_observed_at: Optional[float] = None
    created_at: Optional[float] = None
    scope: Optional[MemoryStoredContextScope] = None


class MemoryCorrectionHistoryResponse(BaseModel):
    target: MemoryCorrectionTarget
    versions: List[MemoryCorrectionVersion] = Field(default_factory=list)
    corrections: List[MemoryCorrectionRecord] = Field(default_factory=list)
    context_labels: Dict[str, str] = Field(default_factory=dict)


class MemoryContextOptionResponse(BaseModel):
    context_id: str = Field(..., pattern=r"^ctx_project_[0-9a-f]{64}$")
    dimension: Literal["project"]
    label: str


class MemoryContextOptionsResponse(BaseModel):
    items: List[MemoryContextOptionResponse] = Field(default_factory=list)


class EpisodeAnnotationRequest(BaseModel):
    user_label: Optional[str] = Field(default=None, max_length=500)
    user_note: Optional[str] = Field(default=None, max_length=2000)
    user_pinned: Optional[bool] = None


class ExperienceAnnotationRequest(BaseModel):
    user_label: Optional[str] = Field(default=None, max_length=500)
    user_note: Optional[str] = Field(default=None, max_length=2000)
    user_pinned: Optional[bool] = None


class ExperienceSeedCreateRequest(BaseModel):
    episode_ids: List[str] = Field(default_factory=list, max_length=100)
    event_ids: List[str] = Field(default_factory=list, max_length=200)
    title_hint: Optional[str] = Field(default=None, max_length=500)
    promote_now: bool = Field(default=False)

    @field_validator("episode_ids", "event_ids", mode="before")
    @classmethod
    def _normalize_ids(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("ids must be a list of strings")
        normalized: List[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                normalized.append(text)
        return normalized


class ExperienceDraftOrganizeRequest(BaseModel):
    query_text: str = Field(..., min_length=2, max_length=1000)
    time_start: Optional[float] = None
    time_end: Optional[float] = None


class ExperienceDraftUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    one_sentence_review: Optional[str] = Field(default=None, max_length=2000)
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    chapters: Optional[List[Dict[str, Any]]] = None
    possible_evidence: Optional[List[Dict[str, Any]]] = None
    excluded_evidence: Optional[List[Dict[str, Any]]] = None


class EpisodeEventIdsRequest(BaseModel):
    event_ids: List[str] = Field(..., min_length=1, max_length=100)

    @field_validator("event_ids", mode="before")
    @classmethod
    def _normalize_event_ids(cls, value: Any) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("event_ids must be a list of strings")
        normalized: List[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                normalized.append(text)
        if not normalized:
            raise ValueError("event_ids must contain at least one non-empty event id")
        return normalized


class EpisodeMergeRequest(BaseModel):
    absorbed_id: str = Field(..., min_length=1, max_length=500)


class EpisodeSplitRequest(BaseModel):
    break_after_event_id: str = Field(..., min_length=1, max_length=500)


class ForgetEntityRequest(BaseModel):
    entity_id: str = Field(..., min_length=1, max_length=500)
    delete_l1_events: bool = Field(
        default=False, description="Also soft-delete L1 events mentioning this entity"
    )


class ForgetTimeRangeRequest(BaseModel):
    start: float = Field(..., description="Range start (epoch seconds)")
    end: float = Field(..., description="Range end (epoch seconds)")
    delete_l1_events: bool = Field(
        default=False, description="Also soft-delete L1 events in this range"
    )

    @field_validator("start", "end")
    @classmethod
    def _require_finite_range_timestamp(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("range timestamp must be finite")
        return value

    @model_validator(mode="after")
    def _require_ordered_range(self) -> "ForgetTimeRangeRequest":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class ForgetEpisodeRequest(BaseModel):
    episode_id: str = Field(..., min_length=1, max_length=500)
    delete_events: bool = Field(default=False, description="Also soft-delete member L1 events")
