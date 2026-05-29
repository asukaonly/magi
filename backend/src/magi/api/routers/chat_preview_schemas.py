"""Request / response models for /api/chat/preview."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from magi.config.models import LLMSettings


class PreviewTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class PreviewMessageRequest(BaseModel):
    seed_slug: str = Field(min_length=1)
    history: list[PreviewTurn] = Field(default_factory=list, max_length=20)
    message: PreviewTurn
    llm_override: Optional[LLMSettings] = Field(
        None, description="Optional unsaved LLM configuration override (onboarding)"
    )
