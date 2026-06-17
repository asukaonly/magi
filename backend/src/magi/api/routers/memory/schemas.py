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
            "event_stream, exact_fact, current_state, episode_recall, summary, strategy, "
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
    mode: str = Field(default="auto", description="Retrieval mode hint, including l1_only for debug-only L1 reads")
    answer_with_llm: bool = Field(default=False, description="Whether to synthesize a final answer with the runtime LLM")
    show_prompt: bool = Field(default=False, description="Whether to include the synthesized LLM prompt in debug output")


class EvalFinalizeReplayRequest(BaseModel):
    period_types: List[str] = Field(
        default_factory=lambda: ["hour", "day", "week", "month"],
        description="Temporal summary categories to generate after replay",
    )


class L2EntityActionBody(BaseModel):
    entity_ids: List[str] = Field(..., description="Canonical entity ids")


class GraphConflictRuleBody(BaseModel):
    opposite_predicates: List[str] = Field(default_factory=list, description="Predicates that conflict as logical opposites")
    opposite_resolution: Literal["mark_deprecated", "mark_conflicted"] = Field(default="mark_deprecated", description="mark_deprecated|mark_conflicted")
    exclusive_group: Optional[str] = Field(default=None, description="Optional mutual-exclusion group")
    exclusive_scope: Literal["same_subject"] = Field(default="same_subject", description="Conflict scope")
    exclusive_resolution: Literal["mark_deprecated", "mark_conflicted"] = Field(default="mark_deprecated", description="mark_deprecated|mark_conflicted")

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


class EpisodeAnnotationRequest(BaseModel):
    user_label: Optional[str] = Field(default=None, max_length=500)
    user_note: Optional[str] = Field(default=None, max_length=2000)
    user_pinned: Optional[bool] = None


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
    delete_l1_events: bool = Field(default=False, description="Also soft-delete L1 events mentioning this entity")


class ForgetTimeRangeRequest(BaseModel):
    start: float = Field(..., description="Range start (epoch seconds)")
    end: float = Field(..., description="Range end (epoch seconds)")
    delete_l1_events: bool = Field(default=False, description="Also soft-delete L1 events in this range")


class ForgetEpisodeRequest(BaseModel):
    episode_id: str = Field(..., min_length=1, max_length=500)
    delete_events: bool = Field(default=False, description="Also soft-delete member L1 events")
