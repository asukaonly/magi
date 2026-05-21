"""Shared helpers for plugin API routes."""

from __future__ import annotations

from importlib import import_module
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import HTTPException, status

from ... import i18n as core_i18n
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

logger = logging.getLogger(__name__)


def normalize_plugin_id(plugin_id: str) -> str:
    """Normalize a plugin_id for plugin i18n lookups.

    Plugin i18n files use the underscored form (e.g. ``chrome_history``) as the
    root key, while the manifest's ``plugin_id`` may use either hyphens or
    underscores (e.g. ``chrome-history`` vs ``git_activity``). This helper
    returns the canonical underscored form so the same key works for either
    style of plugin id.
    """
    return plugin_id.replace("-", "_")


def translate_with_fallback(
    i18n: PluginI18n, key: str, fallback: str | None
) -> str | None:
    """Look up a plugin-i18n key, returning ``fallback`` if missing.

    Returns ``None`` only when both the translation is missing *and* ``fallback``
    is ``None``. Never raises on missing keys.
    """
    if i18n is None:
        return fallback
    try:
        value = i18n.t(key, fallback=None)
    except Exception as exc:  # noqa: BLE001 - defensive: never break serialization
        logger.debug("plugin i18n lookup failed for key=%s: %s", key, exc)
        return fallback
    if not value or value == key:
        return fallback
    return value


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
    plugin_id_normalized = normalize_plugin_id(manifest.plugin_id)

    translated_name = translate_with_fallback(
        i18n, f"{plugin_id_normalized}.name", manifest.name
    )
    translated_description = translate_with_fallback(
        i18n, f"{plugin_id_normalized}.description", manifest.description
    )

    return PluginManifestResponse(
        plugin_id=manifest.plugin_id,
        name=translated_name or manifest.name,
        version=manifest.version,
        description=translated_description or manifest.description,
        author=manifest.author,
        official=manifest.official,
        contribution_types=[item.value for item in manifest.contribution_types],
        source=manifest.source,
        plugin_dir=manifest.plugin_dir,
        manifest_path=manifest.manifest_path,
    )


def _serialize_field(
    field: ExtensionFieldSpec,
    i18n: PluginI18n,
    contribution_id: str,
    plugin_id: str | None = None,
) -> dict[str, Any]:
    """Serialize a field with translation.

    In addition to the legacy ``label`` / ``description`` / ``options[].label``
    keys (which retain the contribution-scoped lookup for backward
    compatibility), the result now includes ``*_translated`` mirrors looked up
    from the plugin's *own* i18n namespace using the plugin-id-normalized
    schema (e.g. ``{chrome_history}.fields.{field_key_short}.label``).
    """
    label_key = f"fields.{contribution_id}.{field.key}.label"
    desc_key = f"fields.{contribution_id}.{field.key}.description"

    field_dict = field.model_dump()
    field_dict["label"] = i18n.t(label_key, fallback=field.label)
    field_dict["description"] = i18n.t(desc_key, fallback=field.description)

    # New plugin-scoped lookups (Phase 1 dual-rail).
    if plugin_id:
        plugin_id_normalized = normalize_plugin_id(plugin_id)
        # Strip the ``sensors.{source}.`` (or similar) prefix to get the short key.
        field_key_short = field.key.split(".")[-1]

        field_dict["label_translated"] = translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.fields.{field_key_short}.label",
            field.label,
        )
        field_dict["description_translated"] = translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.fields.{field_key_short}.description",
            field.description,
        )

    if field_dict.get("options"):
        translated_options = []
        for opt in field_dict["options"]:
            opt_label_key = f"fields.{contribution_id}.{field.key}.options.{opt['value']}"
            entry = {
                "label": i18n.t(opt_label_key, fallback=opt["label"]),
                "value": opt["value"],
            }
            if plugin_id:
                plugin_id_normalized = normalize_plugin_id(plugin_id)
                field_key_short = field.key.split(".")[-1]
                entry["label_translated"] = translate_with_fallback(
                    i18n,
                    f"{plugin_id_normalized}.options.{field_key_short}.{opt['value']}",
                    opt["label"],
                )
            translated_options.append(entry)
        field_dict["options"] = translated_options

    return field_dict


def _serialize_contribution(
    contribution: PluginContribution, i18n: PluginI18n
) -> PluginContributionResponse:
    contribution_id = contribution.contribution_id
    display_name_key = f"contributions.{contribution_id}.display_name"
    description_key = f"contributions.{contribution_id}.description"
    serialized_fields = [
        _serialize_field(field, i18n, contribution_id, plugin_id=contribution.plugin_id)
        for field in contribution.fields
    ]
    metadata = dict(contribution.metadata)
    settings_actions = metadata.get("settings_actions")
    if isinstance(settings_actions, list):
        metadata["settings_actions"] = [
            _serialize_settings_action(item, i18n, plugin_id=contribution.plugin_id)
            for item in settings_actions
            if isinstance(item, dict)
        ]
    settings_ui_blocks = metadata.get("settings_ui_blocks")
    if isinstance(settings_ui_blocks, list):
        metadata["settings_ui_blocks"] = [
            _serialize_settings_ui_block(item, i18n, plugin_id=contribution.plugin_id)
            for item in settings_ui_blocks
            if isinstance(item, dict)
        ]
    activation_flow = metadata.get("activation_flow")
    if isinstance(activation_flow, dict):
        metadata["activation_flow"] = _serialize_activation_flow(
            activation_flow, i18n, plugin_id=contribution.plugin_id
        )

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
        metadata=metadata,
    )


def _serialize_settings_action(
    action: dict[str, Any], i18n: PluginI18n, plugin_id: str | None = None
) -> dict[str, Any]:
    action_id = str(action.get("action_id") or "")
    if not action_id:
        return dict(action)
    translated = dict(action)
    for key in ("label", "description", "button_label"):
        translated[key] = i18n.t(
            f"actions.{action_id}.{key}",
            fallback=str(action.get(key) or ""),
        )
    # New plugin-scoped mirrors (Phase 1 dual-rail).
    if plugin_id:
        plugin_id_normalized = normalize_plugin_id(plugin_id)
        for key in ("label", "description", "button_label"):
            translated[f"{key}_translated"] = translate_with_fallback(
                i18n,
                f"{plugin_id_normalized}.actions.{action_id}.{key}",
                str(action.get(key) or ""),
            )
    return translated


def _serialize_settings_ui_block(
    block: dict[str, Any], i18n: PluginI18n, plugin_id: str | None = None
) -> dict[str, Any]:
    """Augment a settings_ui_block dict with translated mirrors."""
    block_id = str(block.get("block_id") or "")
    out = dict(block)
    if plugin_id and block_id:
        plugin_id_normalized = normalize_plugin_id(plugin_id)
        out["title_translated"] = translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.ui_blocks.{block_id}.title",
            str(block.get("title") or ""),
        )
        out["description_translated"] = translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.ui_blocks.{block_id}.description",
            str(block.get("description") or ""),
        )
    return out


def _serialize_activation_flow(
    flow: dict[str, Any], i18n: PluginI18n, plugin_id: str | None = None
) -> dict[str, Any]:
    """Augment an activation_flow dict with translated mirrors."""
    out = dict(flow)
    if plugin_id:
        plugin_id_normalized = normalize_plugin_id(plugin_id)
        for key in ("title", "description", "confirm_label", "cancel_label"):
            out[f"{key}_translated"] = translate_with_fallback(
                i18n,
                f"{plugin_id_normalized}.activation.{key}",
                str(flow.get(key) or ""),
            )
    return out


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
    logger.info(
        "Installing plugin without active manager",
        extra={
            "plugin_id": entry.plugin_id,
            "source_dir": str(plugin_source),
            "dest_dir": str(dest_dir),
        },
    )
    replace_plugin_directory(plugin_source, dest_dir)

    save_config({f"plugins.packages.{entry.plugin_id}": {"enabled": True}})
    logger.info("Saved lightweight plugin install config", extra={"plugin_id": entry.plugin_id})

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("plugins.errors.not_found", fallback="Plugin not found"),
        )
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
    "_serialize_activation_flow",
    "_serialize_contribution",
    "_serialize_field",
    "_serialize_settings_action",
    "_serialize_settings_ui_block",
    "_serialize_manifest",
    "_serialize_package",
    "_serialize_package_lightweight",
    "_try_plugin_manager",
    "_version_newer",
    "legacy_plugins_module",
    "normalize_plugin_id",
    "translate_with_fallback",
]
