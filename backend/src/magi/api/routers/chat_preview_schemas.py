"""Request / response models for /api/chat/preview."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from magi.config.models import LLMSettings
from magi.api.routers.personality_config_schemas import PersonalityConfigModel


class PreviewTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class PreviewPersonaOverride(PersonalityConfigModel):
    """Complete unsaved persona config for onboarding preview chat."""

    name: str = Field(min_length=1)


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
        None, description="Optional complete inline persona config (onboarding)"
    )
