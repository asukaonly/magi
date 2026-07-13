"""Request / response models for /api/system-suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from magi.system_suggestions.contracts import DismissalKind, SuggestionProposal


class CheckRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    locale: Literal["zh", "en"] = "zh"
    session_id: str = Field(default="default")


class CheckResponse(BaseModel):
    suggestions: list[SuggestionProposal]


class DismissRequest(BaseModel):
    dedupe_key: str = Field(min_length=1)
    kind: DismissalKind
    title: str | None = None
    """Localized text the user saw, stored so the restore list stays consistent."""


class DismissResponse(BaseModel):
    dedupe_key: str
    dismissed: bool


class DismissalItem(BaseModel):
    dedupe_key: str
    dismissed_at: datetime
    kind: DismissalKind
    title: str | None = None


class ListDismissalsResponse(BaseModel):
    dismissals: list[DismissalItem]


class ClearDismissalResponse(BaseModel):
    dedupe_key: str
    cleared: bool


class InstallableItem(BaseModel):
    plugin_id: str
    category: str
    installed: bool
    rationale: dict[str, str]
    setup_time_estimate_seconds: int
    data_locality: Literal["local_only", "uploads"]


class ListInstallableResponse(BaseModel):
    items: list[InstallableItem]
