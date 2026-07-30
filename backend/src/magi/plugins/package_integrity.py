"""Installed plugin identity and ownership validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import PluginSettings
from .contracts import PluginManifest
from .package_files import is_managed_plugin_manifest_path
from .registry_provenance import plugin_manifest_fingerprint


def package_identity_error(
    manifest: PluginManifest,
    configured: PluginSettings | dict[str, Any] | None,
) -> str | None:
    """Return a safe-load rejection reason when persisted identity does not match."""

    if configured is None:
        return None
    if isinstance(configured, dict):
        configured = PluginSettings.model_validate(configured)
    if configured.source != manifest.source:
        return "Plugin source does not match its persisted installation record"
    if manifest.source == "builtin":
        return None

    manifest_path = Path(manifest.manifest_path).expanduser().resolve(strict=False)
    if not configured.manifest_path:
        return "Plugin manifest path is missing from its persisted installation record"
    configured_manifest_path = Path(configured.manifest_path).expanduser().resolve(strict=False)
    if manifest_path != configured_manifest_path:
        return "Plugin manifest path does not match its persisted installation record"

    if configured.install_origin in {"registry", "upload"} and not (
        is_managed_plugin_manifest_path(manifest.plugin_id, manifest.manifest_path)
    ):
        return "Installed plugin is outside Magi's managed plugin directory"

    if configured.install_origin == "registry":
        if not is_verified_registry_package(manifest, configured):
            return "Installed plugin no longer matches its verified marketplace package"
    return None


def is_verified_registry_package(
    manifest: PluginManifest,
    configured: PluginSettings | dict[str, Any] | None,
) -> bool:
    """Return whether a manifest is the exact host-managed registry package."""

    if isinstance(configured, dict):
        configured = PluginSettings.model_validate(configured)
    if configured is None or not isinstance(manifest, PluginManifest):
        return False
    return bool(
        manifest.source == "external"
        and configured.source == "external"
        and configured.install_origin == "registry"
        and configured.registry_source
        and configured.registry_repo_url
        and configured.registry_entry_fingerprint
        and configured.registry_manifest_fingerprint
        and configured.manifest_path
        and Path(configured.manifest_path).expanduser().resolve(strict=False)
        == Path(manifest.manifest_path).expanduser().resolve(strict=False)
        and is_managed_plugin_manifest_path(manifest.plugin_id, manifest.manifest_path)
        and configured.registry_manifest_fingerprint == plugin_manifest_fingerprint(manifest)
    )


__all__ = ["is_verified_registry_package", "package_identity_error"]
