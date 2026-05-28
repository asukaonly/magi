"""Request / response models for /api/chat/preview."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PreviewTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class PreviewMessageRequest(BaseModel):
    seed_slug: str = Field(min_length=1)
    history: list[PreviewTurn] = Field(default_factory=list, max_length=20)
    message: PreviewTurn
