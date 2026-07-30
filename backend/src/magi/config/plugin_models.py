"""Plugin application configuration models."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from magi_plugin_sdk.contracts import PluginCapability


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
    consented_capabilities: Optional[List[PluginCapability]] = Field(
        default=None,
        description="Capabilities the user consented to at install/update. "
        "None means a legacy install predating consent (treated as empty).",
    )
    install_origin: Optional[Literal["builtin", "registry", "upload", "local"]] = Field(
        default=None,
        description="Host-owned package installation origin.",
    )
    registry_source: Optional[str] = Field(
        default=None,
        description="Registry index URL used for this package.",
    )
    registry_repo_url: Optional[str] = Field(
        default=None,
        description="Registry repository URL used to download this package.",
    )
    registry_entry_fingerprint: Optional[str] = Field(
        default=None,
        description="Host-computed fingerprint of the registry entry and source.",
    )
    registry_manifest_fingerprint: Optional[str] = Field(
        default=None,
        description="Host-computed fingerprint of the installed manifest.",
    )
    dependency_entry_fingerprints: Dict[str, str] = Field(
        default_factory=dict,
        description="Approved registry entry fingerprints for direct library dependencies.",
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
            "photo_library_core": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "apple-photos": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "local-photos": PluginSettings(
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
