"""Grounded persona thoughts, separate from facts and relationship milestones."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReflectionCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=500)


class ReflectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["perspective", "self_review", "open_question"]
    topic: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=1200)
    applicability: str = Field(min_length=1, max_length=400)
    citations: list[ReflectionCitation] = Field(min_length=1, max_length=5)


class ReflectionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thoughts: list[ReflectionDraft] = Field(max_length=3)


class ReflectionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: list[bool] = Field(max_length=3)


class PersonaReflection(ReflectionDraft):
    id: str
    persona_id: str
    created_at: float
    status: Literal["active", "dismissed", "stale"]


class ReflectionPage(BaseModel):
    items: list[PersonaReflection]
    enabled: bool
    sharing_enabled: bool
    last_checked_at: float | None = None
    last_status: str | None = None


class ReflectionEvidenceDetail(BaseModel):
    event_id: str
    source: str
    content: str
    occurred_at: float
    session_id: str | None = None


class ReflectionDetail(BaseModel):
    thought: PersonaReflection
    evidence: list[ReflectionEvidenceDetail]


class ReflectionShare(BaseModel):
    thought: PersonaReflection | None = None
