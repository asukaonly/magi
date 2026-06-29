"""Shared helpers for plugin API routes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from ... import i18n as core_i18n
from ...config import get_config
from ...plugins.contracts import (
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
)
from ...plugins.i18n import PluginI18n
from ...plugins.install_service import PluginInstallService
from ...plugins.provider import resolve_plugin_manager
from ...plugins.registry_client import PluginRegistryClient
from .plugins_schemas import (
    PluginContributionResponse,
    PluginManifestResponse,
    PluginPackageResponse,
)

logger = logging.getLogger(__name__)
_registry_client: PluginRegistryClient | None = None


def _authoritative_official(manifest, *, packages) -> bool:
    """Resolve a plugin's official status from the authoritative source.

    builtin plugins are bundled in the app binary, so their manifest is
    trusted. For every other source the local manifest is attacker-authored
    and MUST NOT be trusted — official comes from the registry value
    persisted into config at install time (None/missing → not official).
    """
    if getattr(manifest, "source", None) == "builtin":
        return bool(getattr(manifest, "official", False))
    entry = packages.get(getattr(manifest, "plugin_id", None))
    return bool(getattr(entry, "official", None)) if entry is not None else False


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


def _get_plugin_i18n(plugin_id: str, plugin_dir: str) -> PluginI18n:
    """Get i18n helper for a plugin, using cached instance if plugin is loaded."""
    manager = _try_plugin_manager()
    if manager is not None:
        get_loaded_plugin = getattr(manager, "get_loaded_plugin", None)
        plugin_instance = get_loaded_plugin(plugin_id) if callable(get_loaded_plugin) else None
        if plugin_instance:
            return plugin_instance.i18n
    return PluginI18n(plugin_id, Path(plugin_dir))


def _serialize_manifest(
    manifest: PluginManifest, *, packages=None
) -> PluginManifestResponse:
    i18n = _get_plugin_i18n(manifest.plugin_id, manifest.plugin_dir)
    plugin_id_normalized = normalize_plugin_id(manifest.plugin_id)

    # ``packages`` is the once-read ``config.plugins.packages`` mapping. List
    # endpoints pass it down so serializing M plugins does ONE config read
    # (glob + stat syscalls) instead of M. Single-plugin callers pass None and
    # we read it here, preserving correctness.
    if packages is None:
        packages = get_config().plugins.packages

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
        icon=manifest.icon,
        display_group=manifest.display_group,
        official=_authoritative_official(manifest, packages=packages),
        contribution_types=[item.value for item in manifest.contribution_types],
        source=manifest.source,
        plugin_dir=manifest.plugin_dir,
        manifest_path=manifest.manifest_path,
        capabilities=manifest.capabilities,
        consented_capabilities=(
            packages[manifest.plugin_id].consented_capabilities
            if manifest.plugin_id in packages
            else None
        ),
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
        # Section label lookup: prefer per-plugin override; falls back to the
        # raw section key so the frontend can apply its shared section table.
        section_value = field_dict.get("section")
        if isinstance(section_value, str) and section_value:
            field_dict["section_translated"] = translate_with_fallback(
                i18n,
                f"{plugin_id_normalized}.sections.{section_value}",
                None,
            )
            field_dict["section_note_translated"] = translate_with_fallback(
                i18n,
                f"{plugin_id_normalized}.section_notes.{section_value}",
                None,
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


def _serialize_settings_layout(
    layout: dict[str, Any], i18n: PluginI18n, plugin_id: str | None = None
) -> dict[str, Any]:
    """Augment a plugin-declared settings layout with translated mirrors."""
    out = dict(layout)
    if not plugin_id:
        return out
    plugin_id_normalized = normalize_plugin_id(plugin_id)
    tabs = layout.get("tabs")
    if isinstance(tabs, list):
        translated_tabs: list[Any] = []
        for tab in tabs:
            if not isinstance(tab, dict):
                translated_tabs.append(tab)
                continue
            tab_id = str(tab.get("tab_id") or tab.get("value") or "")
            translated = dict(tab)
            if tab_id:
                translated["label_translated"] = translate_with_fallback(
                    i18n,
                    f"{plugin_id_normalized}.settings_layout.tabs.{tab_id}.label",
                    str(tab.get("label") or ""),
                )
                translated["description_translated"] = translate_with_fallback(
                    i18n,
                    f"{plugin_id_normalized}.settings_layout.tabs.{tab_id}.description",
                    str(tab.get("description") or ""),
                )
                translated["unavailable_reason_translated"] = translate_with_fallback(
                    i18n,
                    f"{plugin_id_normalized}.settings_layout.tabs.{tab_id}.unavailable_reason",
                    tab.get("unavailable_reason"),
                )
            translated_tabs.append(translated)
        out["tabs"] = translated_tabs
    return out


def _serialize_sensor_capability(
    metadata: dict[str, Any],
    i18n: PluginI18n | None,
    *,
    plugin_id: str,
    fallback_source_name: str,
    fallback_display_name: str,
    fallback_description: str,
) -> dict[str, Any]:
    """Serialize the capability/entry grouping metadata for one sensor source."""
    plugin_id_normalized = normalize_plugin_id(plugin_id)
    capability_id = str(metadata.get("capability_id") or fallback_source_name)
    entry_id = str(metadata.get("entry_id") or fallback_source_name)
    capability_display_name = str(
        metadata.get("capability_display_name") or fallback_display_name
    )
    capability_description = str(
        metadata.get("capability_description") or fallback_description
    )
    entry_display_name = str(metadata.get("entry_display_name") or fallback_display_name)
    entry_description = str(metadata.get("entry_description") or fallback_description)
    entry_display_name_translated = translate_with_fallback(
        i18n,
        f"{plugin_id_normalized}.entries.{entry_id}.display_name",
        entry_display_name,
    )
    entry_description_translated = translate_with_fallback(
        i18n,
        f"{plugin_id_normalized}.entries.{entry_id}.description",
        entry_description,
    )
    single_source_capability = capability_id == entry_id
    capability_display_fallback = (
        entry_display_name_translated if single_source_capability else capability_display_name
    )
    capability_description_fallback = (
        entry_description_translated if single_source_capability else capability_description
    )

    return {
        "capability_id": capability_id,
        "capability_display_name": capability_display_name,
        "capability_display_name_translated": translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.capabilities.{capability_id}.display_name",
            capability_display_fallback,
        ),
        "capability_description": capability_description,
        "capability_description_translated": translate_with_fallback(
            i18n,
            f"{plugin_id_normalized}.capabilities.{capability_id}.description",
            capability_description_fallback,
        ),
        "entry_id": entry_id,
        "entry_display_name": entry_display_name,
        "entry_display_name_translated": entry_display_name_translated,
        "entry_description": entry_description,
        "entry_description_translated": entry_description_translated,
    }


def _localize_activation_field(
    field: dict[str, Any], i18n: PluginI18n, plugin_id_normalized: str
) -> dict[str, Any]:
    """Add plugin-scoped ``*_translated`` mirrors to an activation-flow field dict.

    Mirrors the plugin-scoped lookups in :func:`_serialize_field` (which operates
    on :class:`ExtensionFieldSpec` instances) but works on the plain dicts that
    ``ActivationFlowSpec.model_dump()`` produces, so the activation dialog can
    render localized labels / descriptions / option labels.
    """
    out = dict(field)
    key = field.get("key")
    if not isinstance(key, str) or not key:
        return out
    field_key_short = key.split(".")[-1]
    out["label_translated"] = translate_with_fallback(
        i18n,
        f"{plugin_id_normalized}.fields.{field_key_short}.label",
        field.get("label"),
    )
    out["description_translated"] = translate_with_fallback(
        i18n,
        f"{plugin_id_normalized}.fields.{field_key_short}.description",
        field.get("description"),
    )
    options = field.get("options")
    if isinstance(options, list):
        out["options"] = [
            {
                **opt,
                "label_translated": translate_with_fallback(
                    i18n,
                    f"{plugin_id_normalized}.options.{field_key_short}.{opt.get('value')}",
                    opt.get("label"),
                ),
            }
            if isinstance(opt, dict)
            else opt
            for opt in options
        ]
    return out


def _serialize_activation_flow(
    flow: dict[str, Any], i18n: PluginI18n, plugin_id: str | None = None
) -> dict[str, Any]:
    """Augment an activation_flow dict with translated mirrors.

    Adds flow-level ``title`` / ``description`` / ``confirm_label`` /
    ``cancel_label`` mirrors, and localizes each embedded field with the same
    plugin-scoped ``*_translated`` mirrors that :func:`_serialize_field`
    produces for top-level fields.
    """
    out = dict(flow)
    if plugin_id:
        plugin_id_normalized = normalize_plugin_id(plugin_id)
        for key in ("title", "description", "confirm_label", "cancel_label"):
            out[f"{key}_translated"] = translate_with_fallback(
                i18n,
                f"{plugin_id_normalized}.activation.{key}",
                str(flow.get(key) or ""),
            )
        fields = flow.get("fields")
        if isinstance(fields, list):
            out["fields"] = [
                _localize_activation_field(field, i18n, plugin_id_normalized)
                if isinstance(field, dict)
                else field
                for field in fields
            ]
    return out


def _serialize_package(
    state: PluginPackageState, *, packages=None
) -> PluginPackageResponse:
    i18n = _get_plugin_i18n(state.manifest.plugin_id, state.manifest.plugin_dir)

    return PluginPackageResponse(
        manifest=_serialize_manifest(state.manifest, packages=packages),
        enabled=state.enabled,
        trusted=state.trusted,
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[_serialize_contribution(item, i18n) for item in state.contributions],
        current_settings=dict(state.current_settings),
    )


def _serialize_package_lightweight(
    state: PluginPackageState, *, packages=None
) -> PluginPackageResponse:
    """Serialize a PluginPackageState without loading plugin-local i18n."""
    m = state.manifest
    if packages is None:
        packages = get_config().plugins.packages
    return PluginPackageResponse(
        manifest=PluginManifestResponse(
            plugin_id=m.plugin_id,
            name=m.name,
            version=m.version,
            description=m.description,
            author=m.author,
            icon=m.icon,
            display_group=m.display_group,
            official=_authoritative_official(m, packages=packages),
            contribution_types=[ct.value for ct in m.contribution_types],
            source=m.source,
            plugin_dir=m.plugin_dir,
            manifest_path=m.manifest_path,
            capabilities=m.capabilities,
            consented_capabilities=(
                packages[m.plugin_id].consented_capabilities
                if m.plugin_id in packages
                else None
            ),
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
    manager = _require_plugin_manager()
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
    "_plugin_install_service",
    "_require_plugin_manager",
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
    "normalize_plugin_id",
    "resolve_plugin_manager",
    "translate_with_fallback",
]
