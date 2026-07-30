"""Server and feature-flag application configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeatureFlags(BaseModel):
    """Feature flags."""
    enable_three_layer_arch: bool = Field(default=False)
    enable_skills: bool = Field(default=True)
    enable_websocket: bool = Field(default=True)


__all__ = ["FeatureFlags"]
