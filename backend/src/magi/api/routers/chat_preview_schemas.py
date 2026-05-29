"""Request / response models for /api/chat/preview."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from magi.config.models import LLMSettings


class PreviewTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class PreviewPersonaOverride(BaseModel):
    """Inline, unsaved persona identity for previewing a freshly-generated
    persona (onboarding) before it exists as a seed. Carries the same three
    fields the seed loader distills into a flat preview system prompt."""

    name: str = Field(min_length=1)
    identity_statement: str = Field(default="")
    sentence_style: str = Field(default="")


class PreviewMessageRequest(BaseModel):
    # Exactly one persona source is required: a known ``seed_slug`` OR an inline
    # ``persona_override``. The handler returns 400 when neither is provided.
    seed_slug: Optional[str] = Field(default=None)
    # Seed locale folder ("zh" / "en"); selects which bundled preset file the
    # ``seed_slug`` resolves against. Ignored when ``persona_override`` is set.
    locale: str = Field(default="en")
    history: list[PreviewTurn] = Field(default_factory=list, max_length=20)
    message: PreviewTurn
    llm_override: Optional[LLMSettings] = Field(
        None, description="Optional unsaved LLM configuration override (onboarding)"
    )
    persona_override: Optional[PreviewPersonaOverride] = Field(
        None, description="Optional inline persona identity (onboarding)"
    )
