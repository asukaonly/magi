"""Installed plugin identity and ownership validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import PluginSettings
from .contracts import PluginManifest
from .package_files import is_managed_plugin_manifest_path
from .package_identity import (
    PluginPackageIdentityError,
    purge_plugin_bytecode_caches,
    verify_installed_package_sha256,
    verify_installed_source_sha256,
)

_VERIFIED_INSTALL_ORIGINS = frozenset({"registry", "upload", "local"})


def _coerce_plugin_settings(
    configured: PluginSettings | dict[str, Any] | None,
) -> PluginSettings | None:
    if isinstance(configured, dict):
        return PluginSettings.model_validate(configured)
    return configured


def package_install_record_error(
    manifest: PluginManifest,
    configured: PluginSettings | dict[str, Any] | None,
) -> str | None:
    """Return a cheap rejection reason for persisted package ownership metadata."""

    configured = _coerce_plugin_settings(configured)
    if configured is None:
        return None
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

    is_managed_package = is_managed_plugin_manifest_path(
        manifest.plugin_id,
        manifest.manifest_path,
    )
    if is_managed_package and configured.install_origin not in {
        *_VERIFIED_INSTALL_ORIGINS,
        "local",
    }:
        return "Managed plugin installation origin is missing from its installation record"
    if configured.install_origin in _VERIFIED_INSTALL_ORIGINS and not is_managed_package:
        return "Installed plugin is outside Magi's managed plugin directory"

    if configured.install_origin not in _VERIFIED_INSTALL_ORIGINS:
        return None
    if configured.install_origin == "registry" and not (
        configured.registry_source and configured.registry_repo_url
    ):
        return "Marketplace plugin source is missing from its persisted installation record"
    if not configured.package_sha256:
        return "Installed plugin package digest is missing from its installation record"
    if not configured.installed_package_sha256:
        return "Installed plugin seal is missing from its installation record"
    return None


def package_identity_error(
    manifest: PluginManifest,
    configured: PluginSettings | dict[str, Any] | None,
) -> str | None:
    """Return a safe-load rejection reason after complete on-disk verification."""

    record_error = package_install_record_error(manifest, configured)
    if record_error is not None:
        return record_error
    configured = _coerce_plugin_settings(configured)
    if (
        configured is None
        or manifest.source == "builtin"
        or configured.install_origin not in _VERIFIED_INSTALL_ORIGINS
    ):
        return None
    assert configured.package_sha256 is not None
    assert configured.installed_package_sha256 is not None
    try:
        plugin_dir = Path(manifest.plugin_dir)
        purge_plugin_bytecode_caches(plugin_dir)
        verify_installed_source_sha256(
            plugin_dir,
            configured.package_sha256,
        )
        verify_installed_package_sha256(
            plugin_dir,
            configured.installed_package_sha256,
        )
    except PluginPackageIdentityError as exc:
        return f"Installed plugin package integrity check failed: {exc}"
    return None


def has_registry_install_record(
    manifest: PluginManifest,
    configured: PluginSettings | dict[str, Any] | None,
) -> bool:
    """Return whether cheap persisted metadata describes one marketplace install."""

    configured = _coerce_plugin_settings(configured)
    return bool(
        isinstance(manifest, PluginManifest)
        and configured is not None
        and manifest.source == "external"
        and configured.source == "external"
        and configured.install_origin == "registry"
        and package_install_record_error(manifest, configured) is None
    )


def is_verified_registry_package(
    manifest: PluginManifest,
    configured: PluginSettings | dict[str, Any] | None,
) -> bool:
    """Return whether a manifest is the exact host-managed registry package."""

    return bool(
        has_registry_install_record(manifest, configured)
        and package_identity_error(manifest, configured) is None
    )


__all__ = [
    "has_registry_install_record",
    "is_verified_registry_package",
    "package_identity_error",
    "package_install_record_error",
]
