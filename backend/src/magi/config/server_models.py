"""Server and feature-flag application configuration models."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ServerSettings(BaseModel):
    """Server configuration."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = Field(default=True)
    debug: bool = Field(default=False)
    desktop_session_token: str = Field(default="")
    cors_origins: List[str] = Field(default=["*"])


class FeatureFlags(BaseModel):
    """Feature flags."""
    enable_three_layer_arch: bool = Field(default=False)
    enable_skills: bool = Field(default=True)
    enable_websocket: bool = Field(default=True)


__all__ = ["FeatureFlags", "ServerSettings"]