"""Pydantic schemas for memory API routes."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
    flush_l2: bool = Field(
        default=True,
        description="Whether to flush staged L2 batches into extraction jobs.",
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
    feedback: Literal["confirmed", "rejected"]


class AssertionCorrectionRequest(BaseModel):
    new_value: str = Field(..., min_length=1, max_length=2000)
    reason: Optional[str] = Field(default=None, max_length=500)


class MemoryCorrectionTarget(BaseModel):
    kind: Literal["assertion", "edge"]
    id: str = Field(..., min_length=1, max_length=200)


class MemoryCorrectionRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=200)
    target: MemoryCorrectionTarget
    correction_kind: Literal["record_error", "situation_changed", "scope_refinement"]
    replacement: Optional[Dict[str, Any]] = None
    reason: Optional[str] = Field(default=None, max_length=2000)
    effective_at: Optional[float] = None
    scope: Optional[Dict[str, Any]] = None
    source_event_id: Optional[str] = Field(default=None, max_length=200)
    expected_updated_at: Optional[float] = None


class MemoryCorrectionRevertRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=200)


class MemoryCorrectionRecord(BaseModel):
    correction_id: str
    request_id: str
    actor_id: str
    target_kind: Literal["assertion", "edge"]
    target_id: str
    slot_key: str
    claim_fingerprint: str
    correction_kind: Literal["record_error", "situation_changed", "scope_refinement"]
    before: Dict[str, Any]
    created_at: float
    state: Literal["active", "reverted"]
    reason: Optional[str] = None
    replacement: Optional[Dict[str, Any]] = None
    effective_at: Optional[float] = None
    scope: Optional[Dict[str, Any]] = None
    source_event_id: Optional[str] = None
    audit_event_id: Optional[str] = None
    replacement_target_id: Optional[str] = None
    reverted_at: Optional[float] = None
    reverted_by: Optional[str] = None


class MemoryCorrectionCommandResponse(BaseModel):
    correction: MemoryCorrectionRecord
    current_claim: Optional[Dict[str, Any]] = None
    subject_revision: Optional[int] = None
    derivation_state: Literal["pending", "running", "completed", "failed"]
    created: bool


class MemoryCorrectionHistoryResponse(BaseModel):
    target: MemoryCorrectionTarget
    versions: List[Dict[str, Any]] = Field(default_factory=list)
    corrections: List[MemoryCorrectionRecord] = Field(default_factory=list)


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


class ForgetEpisodeRequest(BaseModel):
    episode_id: str = Field(..., min_length=1, max_length=500)
    delete_events: bool = Field(default=False, description="Also soft-delete member L1 events")
