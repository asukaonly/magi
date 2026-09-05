"""Plugin API response serialization helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...config import get_config
from ...plugins.contracts import (
    ExtensionFieldSpec,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
)
from ...plugins.i18n import PluginI18n
from ...plugins.icon_assets import resolve_plugin_icon
from ...plugins.package_integrity import has_registry_install_record
from ...plugins.provider import resolve_plugin_manager
from ...plugins.registry_client import is_official_registry_source
from ..services.plugin_secrets import mask_plugin_settings
from .plugins_schemas import (
    PluginContributionResponse,
    PluginManifestResponse,
    PluginPackageResponse,
)

logger = logging.getLogger(__name__)


def _authoritative_official(manifest, *, packages, trusted: bool = False) -> bool:
    """Resolve a plugin's official status from the authoritative source."""
    if getattr(manifest, "source", None) == "builtin":
        return bool(getattr(manifest, "official", False))
    entry = packages.get(getattr(manifest, "plugin_id", None))
    return bool(
        entry is not None
        and trusted
        and getattr(entry, "official", None)
        and has_registry_install_record(manifest, entry)
        and is_official_registry_source(
            getattr(entry, "registry_source", None),
            getattr(entry, "registry_repo_url", None),
        )
    )


def normalize_plugin_id(plugin_id: str) -> str:
    """Normalize a plugin_id for plugin i18n lookups."""
    return plugin_id.replace("-", "_")


def translate_with_fallback(i18n: PluginI18n, key: str, fallback: str | None) -> str | None:
    """Look up a plugin-i18n key, returning ``fallback`` if missing."""
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


def _try_plugin_manager():
    try:
        return resolve_plugin_manager()
    except RuntimeError:
        return None


def _get_plugin_i18n(plugin_id: str, plugin_dir: str) -> PluginI18n:
    """Read package translations without selecting or executing a connection."""
    return PluginI18n(plugin_id, Path(plugin_dir))


def _serialize_manifest(
    manifest: PluginManifest,
    *,
    packages=None,
    trusted: bool = False,
) -> PluginManifestResponse:
    i18n = _get_plugin_i18n(manifest.plugin_id, manifest.plugin_dir)
    plugin_id_normalized = normalize_plugin_id(manifest.plugin_id)

    if packages is None:
        packages = get_config().plugins.packages

    translated_name = translate_with_fallback(i18n, f"{plugin_id_normalized}.name", manifest.name)
    translated_description = translate_with_fallback(
        i18n, f"{plugin_id_normalized}.description", manifest.description
    )

    return PluginManifestResponse(
        protocol_version=manifest.protocol_version,
        min_sdk_version=manifest.min_sdk_version,
        execution_mode=manifest.execution_mode,
        activation_flow=_serialize_activation_flow(manifest.activation_flow.model_dump(), i18n, manifest.plugin_id) if manifest.activation_flow else None,
        settings_actions=[_serialize_settings_action(item.model_dump(), i18n, manifest.plugin_id) for item in manifest.settings_actions],
        settings_resources=[item.model_dump() for item in manifest.settings_resources],
        settings_ui_blocks=[_serialize_settings_ui_block(item.model_dump(), i18n, manifest.plugin_id) for item in manifest.settings_ui_blocks],
        settings_fields=[
            _serialize_field(field, i18n, manifest.plugin_id, manifest.plugin_id)
            for field in manifest.settings_fields
        ],
        plugin_id=manifest.plugin_id,
        name=translated_name or manifest.name,
        version=manifest.version,
        description=translated_description or manifest.description,
        author=manifest.author,
        icon=resolve_plugin_icon(manifest.icon, manifest.plugin_dir),
        display_group=manifest.display_group,
        official=_authoritative_official(manifest, packages=packages, trusted=trusted),
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
    """Serialize a field with translation."""
    label_key = f"fields.{contribution_id}.{field.key}.label"
    desc_key = f"fields.{contribution_id}.{field.key}.description"

    field_dict = field.model_dump()
    if field.type == "secret":
        field_dict["default"] = ""
    field_dict["label"] = i18n.t(label_key, fallback=field.label)
    field_dict["description"] = i18n.t(desc_key, fallback=field.description)

    if plugin_id:
        plugin_id_normalized = normalize_plugin_id(plugin_id)
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


def _serialize_source_capability(
    metadata: dict[str, Any],
    i18n: PluginI18n | None,
    *,
    plugin_id: str,
    fallback_source_name: str,
    fallback_display_name: str,
    fallback_description: str,
) -> dict[str, Any]:
    """Serialize the capability/entry grouping metadata for one source."""
    plugin_id_normalized = normalize_plugin_id(plugin_id)
    capability_id = str(metadata.get("capability_id") or fallback_source_name)
    entry_id = str(metadata.get("entry_id") or fallback_source_name)
    capability_display_name = str(metadata.get("capability_display_name") or fallback_display_name)
    capability_description = str(metadata.get("capability_description") or fallback_description)
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
    """Add plugin-scoped translation mirrors to an activation-flow field dict."""
    out = dict(field)
    if field.get("type") == "secret":
        out["default"] = ""
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
            (
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
            )
            for opt in options
        ]
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
        fields = flow.get("fields")
        if isinstance(fields, list):
            out["fields"] = [
                (
                    _localize_activation_field(field, i18n, plugin_id_normalized)
                    if isinstance(field, dict)
                    else field
                )
                for field in fields
            ]
    return out


def _serialize_package(state: PluginPackageState, *, packages=None) -> PluginPackageResponse:
    i18n = _get_plugin_i18n(state.manifest.plugin_id, state.manifest.plugin_dir)
    if packages is None:
        packages = get_config().plugins.packages
    package_config = packages.get(state.manifest.plugin_id)

    return PluginPackageResponse(
        manifest=_serialize_manifest(
            state.manifest,
            packages=packages,
            trusted=state.trusted,
        ),
        enabled=state.enabled,
        trusted=state.trusted,
        package_sha256=getattr(package_config, "package_sha256", None),
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[_serialize_contribution(item, i18n) for item in state.contributions],
        current_settings=mask_plugin_settings(state.current_settings, state.contributions),
    )


def _serialize_package_lightweight(
    state: PluginPackageState, *, packages=None
) -> PluginPackageResponse:
    """Serialize a PluginPackageState without loading plugin-local i18n."""
    manifest = state.manifest
    if packages is None:
        packages = get_config().plugins.packages
    return PluginPackageResponse(
        manifest=PluginManifestResponse(
            protocol_version=manifest.protocol_version,
            min_sdk_version=manifest.min_sdk_version,
            execution_mode=manifest.execution_mode,
            settings_fields=[{**item.model_dump(), **({"default": ""} if item.type == "secret" else {})} for item in manifest.settings_fields],
            activation_flow=manifest.activation_flow.model_dump() if manifest.activation_flow else None,
            settings_actions=[item.model_dump() for item in manifest.settings_actions],
            settings_resources=[item.model_dump() for item in manifest.settings_resources],
            settings_ui_blocks=[item.model_dump() for item in manifest.settings_ui_blocks],
            plugin_id=manifest.plugin_id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            icon=resolve_plugin_icon(manifest.icon, manifest.plugin_dir),
            display_group=manifest.display_group,
            official=_authoritative_official(
                manifest,
                packages=packages,
                trusted=state.trusted,
            ),
            contribution_types=[ct.value for ct in manifest.contribution_types],
            source=manifest.source,
            plugin_dir=manifest.plugin_dir,
            manifest_path=manifest.manifest_path,
            capabilities=manifest.capabilities,
            consented_capabilities=(
                packages[manifest.plugin_id].consented_capabilities
                if manifest.plugin_id in packages
                else None
            ),
        ),
        enabled=state.enabled,
        trusted=state.trusted,
        package_sha256=getattr(packages.get(manifest.plugin_id), "package_sha256", None),
        loaded=state.loaded,
        healthy=state.healthy,
        last_error=state.last_error,
        contributions=[],
        current_settings=mask_plugin_settings(state.current_settings, state.contributions),
    )


__all__ = [
    "_authoritative_official",
    "_get_plugin_i18n",
    "_localize_activation_field",
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
    "normalize_plugin_id",
    "translate_with_fallback",
]
