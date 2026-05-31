"""Plugin application configuration models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PluginSettings(BaseModel):
    """Per-plugin persisted runtime state."""

    enabled: bool = Field(default=False)
    trusted: bool = Field(default=False)
    settings: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = Field(default=None)
    manifest_path: Optional[str] = Field(default=None)
    official: Optional[bool] = Field(
        default=None,
        description="Registry-authoritative official flag for non-builtin "
        "plugins; None means unknown (treated as non-official).",
    )


class PluginsSettings(BaseModel):
    """Unified plugin runtime configuration."""

    scan_paths: List[str] = Field(default_factory=lambda: ["plugins", "~/.magi/plugins"])
    registry_url: Optional[str] = Field(default=None)
    packages: Dict[str, PluginSettings] = Field(
        default_factory=lambda: {
            "core-tools": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "photo-library": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "chrome-history": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "calendar": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "git-activity": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "screen-time": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "terminal-history": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
        }
    )


__all__ = ["PluginSettings", "PluginsSettings"]