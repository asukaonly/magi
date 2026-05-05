"""Shared helpers for plugin API routes."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import HTTPException, status

from ...plugins.contracts import (
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
)
from ...plugins.i18n import PluginI18n
from ...plugins.installation import replace_plugin_directory
from ...plugins.registry_client import PluginRegistryClient
from .plugins_schemas import (
    PluginContributionResponse,
    PluginManifestResponse,
    PluginPackageResponse,
)


def legacy_plugins_module() -> ModuleType:
    return import_module("magi.api.routers.plugins")


def _get_registry_client() -> PluginRegistryClient:
    """Return a shared registry client so the TTL cache is effective."""
    legacy = legacy_plugins_module()
    if legacy._registry_client is None:
        legacy._registry_client = legacy.PluginRegistryClient()
    return legacy._registry_client


def _try_plugin_manager():
    """Return the plugin manager if initialized, otherwise ``None``."""
    legacy = legacy_plugins_module()
    try:
        return legacy.resolve_plugin_manager()
    except RuntimeError:
        return None


def _get_plugin_i18n(plugin_id: str, plugin_dir: str) -> PluginI18n:
    """Get i18n helper for a plugin, using cached instance if plugin is loaded."""
    legacy = legacy_plugins_module()
    manager = legacy._try_plugin_manager()
    if manager is not None:
        plugin_instance = manager._plugin_instances.get(plugin_id)
        if plugin_instance:
            return plugin_instance.i18n
    return legacy.PluginI18n(plugin_id, Path(plugin_dir))


def _serialize_manifest(manifest: PluginManifest) -> PluginManifestResponse:
    legacy = legacy_plugins_module()
    i18n = legacy._get_plugin_i18n(manifest.plugin_id, manifest.plugin_dir)
    plugin_id = manifest.plugin_id

    translated_name = i18n.t(f"{plugin_id}.name", fallback=manifest.name)
    translated_description = i18n.t(f"{plugin_id}.description", fallback=manifest.description)

    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=translated_name,
        version=manifest.version,
        description=translated_description,
        author=manifest.author,
        official=manifest.official,
        contribution_types=[item.value for item in manifest.contribution_types],
        source=manifest.source,
        plugin_dir=manifest.plugin_dir,
        manifest_path=manifest.manifest_path,
    )


def _serialize_field(field: ExtensionFieldSpec, i18n: PluginI18n, contribution_id: str) -> dict[str, Any]:
    """Serialize a field with translation."""
    label_key = f"fields.{contribution_id}.{field.key}.label"
    desc_key = f"fields.{contribution_id}.{field.key}.description"

    field_dict = field.model_dump()
    field_dict["label"] = i18n.t(label_key, fallback=field.label)
    field_dict["description"] = i18n.t(desc_key, fallback=field.description)

    if field_dict.get("options"):
        translated_options = []
        for opt in field_dict["options"]:
            opt_label_key = f"fields.{contribution_id}.{field.key}.options.{opt['value']}"
            translated_options.append({"label": i18n.t(opt_label_key, fallback=opt["label"]), "value": opt["value"]})
        field_dict["options"] = translated_options

    return field_dict


def _serialize_contribution(contribution: PluginContribution, i18n: PluginI18n) -> PluginContributionResponse:
    contribution_id = contribution.contribution_id
    display_name_key = f"contributions.{contribution_id}.display_name"
    description_key = f"contributions.{contribution_id}.description"
    serialized_fields = [_serialize_field(field, i18n, contribution_id) for field in contribution.fields]

    return PluginContributionResponse(
        plugin_id=contribution.plugin_id,
        contribution_id=contribution.contribution_id,
        contribution_type=(
            contribution.contribution_type.value
            if hasattr(contribution.contribution_type, "value")
            else str(contribution.contribution_type)
        ),
        display_name=i18n.t(display_name_key, fallback=contribution.display_name),
        description=i18n.t(description_key, fallback=contribution.description),
        surface=contribution.surface,
        fields=serialized_fields,
        metadata=dict(contribution.metadata),
    )


def _lightweight_install(source_dir: Path, entry: PluginRegistryEntry) -> PluginPackageState:
    """Install plugin files without a running PluginManager."""
    from ...config import save_config
    from ...plugins.contracts import ContributionType
    from ...plugins.manager import PluginManager

    manifest_file = PluginManager._find_manifest_in_tree(source_dir)
    if manifest_file is None:
        raise ValueError("Directory does not contain a plugin.toml")

    plugin_source = manifest_file.parent
    user_root = PluginManager._user_plugins_root()
    user_root.mkdir(parents=True, exist_ok=True)
    dest_dir = user_root / entry.plugin_id
    replace_plugin_directory(plugin_source, dest_dir)

    save_config({f"plugins.packages.{entry.plugin_id}": {"enabled": True}})

    ctypes: list[ContributionType] = []
    for ct in entry.contribution_types:
        try:
            ctypes.append(ContributionType(ct))
        except ValueError:
            pass

    return PluginPackageState(
        manifest=PluginManifest(
            id=entry.plugin_id,
            name=entry.name,
            version=entry.version,
            description=entry.description,
            author=entry.author,
            official=entry.official,
            contribution_types=ctypes,
            platforms=entry.platforms,
            plugin_dir=str(dest_dir),
            source="external",
        ),
        enabled=True,
        trusted=False,
        loaded=False,
        healthy=True,
    )


def _serialize_package(state: PluginPackageState) -> PluginPackageResponse:
    legacy = legacy_plugins_module()
    i18n = legacy._get_plugin_i18n(state.manifest.plugin_id, state.manifest.plugin_dir)

    return PluginPackageResponse(
        manifest=legacy._serialize_manifest(state.manifest),
        enabled=state.enabled,
        trusted=state.trusted,
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[legacy._serialize_contribution(item, i18n) for item in state.contributions],
        current_settings=dict(state.current_settings),
    )


def _serialize_package_lightweight(state: PluginPackageState) -> PluginPackageResponse:
    """Serialize a PluginPackageState without loading plugin-local i18n."""
    m = state.manifest
    return PluginPackageResponse(
        manifest=PluginManifestResponse(
            plugin_id=m.plugin_id,
            name=m.name,
            version=m.version,
            description=m.description,
            author=m.author,
            official=m.official,
            contribution_types=[ct.value for ct in m.contribution_types],
            source=m.source,
            plugin_dir=m.plugin_dir,
            manifest_path=m.manifest_path,
        ),
        enabled=state.enabled,
        trusted=state.trusted,
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[],
        current_settings=dict(state.current_settings),
    )


def _require_package(plugin_id: str):
    legacy = legacy_plugins_module()
    manager = legacy.resolve_plugin_manager()
    package = manager.get_package(plugin_id)
    if package is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    return manager, package


def _version_newer(remote: str, local: str) -> bool:
    """Compare semver-style version strings (best-effort)."""
    try:
        remote_parts = [int(p) for p in remote.split(".")]
        local_parts = [int(p) for p in local.split(".")]
        return remote_parts > local_parts
    except (ValueError, AttributeError):
        return remote != local


__all__ = [
    "_get_plugin_i18n",
    "_get_registry_client",
    "_lightweight_install",
    "_require_package",
    "_serialize_contribution",
    "_serialize_field",
    "_serialize_manifest",
    "_serialize_package",
    "_serialize_package_lightweight",
    "_try_plugin_manager",
    "_version_newer",
    "legacy_plugins_module",
]