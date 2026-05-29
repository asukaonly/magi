"""Request / response models for /api/system-suggestions."""

from __future__ import annotations

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


class DismissResponse(BaseModel):
    dedupe_key: str
    dismissed: bool
