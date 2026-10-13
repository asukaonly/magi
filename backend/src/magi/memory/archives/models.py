"""Typed historical archive search contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArchiveRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    record_id: str = Field(min_length=1)
    layer: Literal["l1", "l3"]
    content: str
    source: str
    event_type: str
    occurred_at: float
    period_end: float | None = None
    archived_at: float
    evidence_event_ids: list[str]
    archived: Literal[True] = True


class ArchiveSearchIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal["archive_unreadable", "archive_unsafe", "record_invalid"]
    count: int = Field(ge=1)


class ArchiveSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ArchiveRecord]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=10000)
    partial: bool = False
    issues: list[ArchiveSearchIssue] = Field(default_factory=list)
