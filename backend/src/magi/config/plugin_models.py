"""Plugin application configuration models."""

from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from magi_plugin_sdk.contracts import PluginCapability, PluginIdentifier

_PackageSha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PluginSettings(BaseModel):
    """Installation identity, trust and consent; runtime state belongs to connections."""

    model_config = ConfigDict(extra="forbid", strict=True)

    trusted: bool = Field(default=False)
    source: Optional[Literal["builtin", "external"]] = Field(default=None)
    manifest_path: Optional[str] = Field(default=None)
    official: Optional[bool] = Field(
        default=None,
        description="Registry-authoritative official flag for non-builtin "
        "plugins; None means unknown (treated as non-official).",
    )
    consented_capabilities: Optional[List[PluginCapability]] = Field(
        default=None,
        description="Capabilities the user consented to at install/update. "
        "None means no capability consent has been recorded.",
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
    package_sha256: Optional[_PackageSha256] = Field(
        default=None,
        description="Verified upstream SHA-256 identity of the distributed plugin package.",
    )
    installed_package_sha256: Optional[_PackageSha256] = Field(
        default=None,
        description="Host-generated SHA-256 seal of the complete local installation.",
    )
    dependency_package_sha256: Dict[PluginIdentifier, _PackageSha256] = Field(
        default_factory=dict,
        description="Verified package SHA-256 identities for direct plugin dependencies.",
    )


class PluginsSettings(BaseModel):
    """Unified plugin runtime configuration."""

    scan_paths: List[str] = Field(default_factory=lambda: ["plugins", "~/.magi/plugins"])
    registry_url: Optional[str] = Field(default=None)
    packages: Dict[PluginIdentifier, PluginSettings] = Field(default_factory=dict)


__all__ = ["PluginSettings", "PluginsSettings"]
