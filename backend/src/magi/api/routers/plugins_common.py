"""Shared helpers for plugin API routes."""

from __future__ import annotations

from fastapi import HTTPException, status
from magi_plugin_sdk.versioning import is_plugin_version_newer as _version_newer

from ... import i18n as core_i18n
from ...plugins.install_service import PluginInstallService
from ...plugins.provider import resolve_plugin_manager
from ...plugins.registry_client import PluginRegistryClient
from .plugins_serialization import (
    _authoritative_official,
    _get_plugin_i18n,
    _serialize_activation_flow,
    _serialize_contribution,
    _serialize_field,
    _serialize_manifest,
    _serialize_package,
    _serialize_package_lightweight,
    _serialize_source_capability,
    _serialize_settings_action,
    _serialize_settings_layout,
    _serialize_settings_ui_block,
    normalize_plugin_id,
    translate_with_fallback,
)

_registry_client: PluginRegistryClient | None = None


def _get_registry_client() -> PluginRegistryClient:
    """Return a shared registry client so the TTL cache is effective."""
    global _registry_client
    if _registry_client is None:
        _registry_client = PluginRegistryClient()
    return _registry_client


def _try_plugin_manager():
    """Return the plugin manager if initialized, otherwise ``None``."""
    try:
        return _require_plugin_manager()
    except RuntimeError:
        return None


def _require_plugin_manager():
    """Return the initialized plugin manager or raise the provider error."""
    return resolve_plugin_manager()


def _plugin_install_service(manager=None) -> PluginInstallService:
    return PluginInstallService(
        registry_client=_get_registry_client(),
        plugin_manager=manager,
    )


def _require_package(plugin_id: str):
    manager = _require_plugin_manager()
    package = manager.get_package(plugin_id)
    if package is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("plugins.errors.not_found", fallback="Plugin not found"),
        )
    return manager, package


__all__ = [
    "_authoritative_official",
    "_get_plugin_i18n",
    "_get_registry_client",
    "_plugin_install_service",
    "_require_plugin_manager",
    "_require_package",
    "_serialize_activation_flow",
    "_serialize_contribution",
    "_serialize_field",
    "_serialize_manifest",
    "_serialize_package",
    "_serialize_package_lightweight",
    "_serialize_source_capability",
    "_serialize_settings_action",
    "_serialize_settings_layout",
    "_serialize_settings_ui_block",
    "_try_plugin_manager",
    "_version_newer",
    "normalize_plugin_id",
    "resolve_plugin_manager",
    "translate_with_fallback",
]
