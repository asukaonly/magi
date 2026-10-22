"""Validated user commands for experience application workflows."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ExperienceAnnotationRequest(BaseModel):
    expected_revision: str | None = None
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
    expected_updated_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    one_sentence_review: Optional[str] = Field(default=None, max_length=2000)
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    chapters: Optional[List[Dict[str, Any]]] = None
    possible_evidence: Optional[List[Dict[str, Any]]] = None
    excluded_evidence: Optional[List[Dict[str, Any]]] = None
