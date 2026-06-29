"""Plugin management API router facade."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status

from ...plugins.contracts import (
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
    PluginSettingsResourcePayload,
)
from ...plugins.i18n import PluginI18n
from ...plugins.provider import resolve_plugin_manager
from ...plugins.registry_client import PluginRegistryClient
from .plugins_common import (
    _get_plugin_i18n,
    _get_registry_client,
    _plugin_install_service,
    _require_package,
    _serialize_contribution,
    _serialize_field,
    _serialize_manifest,
    _serialize_package,
    _serialize_package_lightweight,
    _try_plugin_manager,
    _version_newer,
)
from .plugins_core_routes import (
    disable_plugin,
    enable_plugin,
    get_plugin_settings,
    list_plugins,
    cancel_plugin_settings_action,
    poll_plugin_settings_action,
    plugins_core_router,
    read_plugin_settings_resource,
    reload_plugin,
    rescan_plugins,
    start_plugin_settings_action,
    update_plugin_settings,
)
from .plugins_install_routes import (
    get_plugin_install_job,
    install_plugin_from_registry,
    install_plugin_from_upload,
    plugins_install_router,
    start_plugin_registry_install_job,
    start_plugin_upload_install_job,
    uninstall_plugin,
)
from .plugins_registry_routes import (
    check_plugin_updates,
    list_registry_plugins,
    plugins_registry_router,
    start_plugin_update_job,
    update_plugin,
)
from .plugins_schemas import (
    PluginContributionResponse,
    PluginInstallRequest,
    PluginManifestResponse,
    PluginPackageResponse,
    PluginRegistryEntryResponse,
    PluginRegistryResponse,
    PluginSettingsActionRequest,
    PluginSettingsActionRunResponse,
    PluginSettingsResourceResponse,
    PluginSettingsUpdateRequest,
    PluginUpdateCheckResponse,
    PluginsListResponse,
)

logger = logging.getLogger(__name__)
plugins_router = plugins_core_router

_registry_client: PluginRegistryClient | None = None

plugins_router.include_router(plugins_install_router)
plugins_router.include_router(plugins_registry_router)

__all__ = [
    "APIRouter",
    "ExtensionFieldSpec",
    "HTTPException",
    "Path",
    "PluginContribution",
    "PluginContributionResponse",
    "PluginI18n",
    "PluginInstallRequest",
    "PluginManifest",
    "PluginManifestResponse",
    "PluginPackageResponse",
    "PluginPackageState",
    "PluginRegistryEntry",
    "PluginRegistryEntryResponse",
    "PluginRegistryIndex",
    "PluginRegistryResponse",
    "PluginSettingsActionRequest",
    "PluginSettingsActionRunResponse",
    "PluginSettingsResourcePayload",
    "PluginSettingsResourceResponse",
    "PluginSettingsUpdateRequest",
    "PluginUpdateCheckResponse",
    "PluginsListResponse",
    "UploadFile",
    "_get_plugin_i18n",
    "_get_registry_client",
    "_plugin_install_service",
    "_registry_client",
    "_require_package",
    "_serialize_contribution",
    "_serialize_field",
    "_serialize_manifest",
    "_serialize_package",
    "_serialize_package_lightweight",
    "_try_plugin_manager",
    "_version_newer",
    "check_plugin_updates",
    "cancel_plugin_settings_action",
    "disable_plugin",
    "enable_plugin",
    "get_plugin_settings",
    "get_plugin_install_job",
    "install_plugin_from_registry",
    "install_plugin_from_upload",
    "list_plugins",
    "list_registry_plugins",
    "logger",
    "plugins_router",
    "poll_plugin_settings_action",
    "read_plugin_settings_resource",
    "reload_plugin",
    "rescan_plugins",
    "resolve_plugin_manager",
    "shutil",
    "status",
    "start_plugin_registry_install_job",
    "start_plugin_update_job",
    "start_plugin_upload_install_job",
    "start_plugin_settings_action",
    "tempfile",
    "uninstall_plugin",
    "update_plugin",
    "update_plugin_settings",
]
