"""Write-only projections for plugin-declared secret settings."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from ...utils.log_redaction import is_sensitive_log_field

MASKED_PLUGIN_SECRET = "***"
_MISSING = object()


def declared_plugin_secret_keys(contributions: Iterable[Any]) -> set[str]:
    """Collect settings keys declared as secret by plugin UI contracts."""
    keys: set[str] = set()
    for contribution in contributions:
        for field in getattr(contribution, "fields", []) or []:
            key = str(getattr(field, "key", "") or "")
            if key and getattr(field, "type", None) == "secret":
                keys.add(key)

        metadata = getattr(contribution, "metadata", {}) or {}
        activation_flow = metadata.get("activation_flow")
        if not isinstance(activation_flow, dict):
            continue
        for field in activation_flow.get("fields", []) or []:
            if not isinstance(field, dict) or field.get("type") != "secret":
                continue
            key = field.get("key")
            if isinstance(key, str) and key:
                keys.add(key)
    return keys


def is_plugin_secret_key(key: str, contributions: Iterable[Any]) -> bool:
    """Return whether a setting is schema-declared or clearly named as secret."""
    return key in declared_plugin_secret_keys(contributions) or is_sensitive_log_field(key)


def mask_plugin_settings(
    settings: dict[str, Any],
    contributions: Iterable[Any],
) -> dict[str, Any]:
    """Copy plugin settings and replace readable secret values with a sentinel."""
    masked = deepcopy(settings)
    candidate_keys = declared_plugin_secret_keys(contributions)
    candidate_keys.update(_sensitive_leaf_paths(masked))
    for key in candidate_keys:
        value = _get_setting(masked, key, _MISSING)
        if value is _MISSING:
            continue
        _set_existing_setting(masked, key, MASKED_PLUGIN_SECRET if value else value)
    return masked


def normalize_masked_plugin_updates(
    updates: dict[str, Any],
    existing_settings: dict[str, Any],
    contributions: Iterable[Any],
) -> dict[str, Any]:
    """Resolve secret sentinels without weakening replace or explicit-delete behavior."""
    normalized = deepcopy(updates)
    for key, value in list(normalized.items()):
        if value != MASKED_PLUGIN_SECRET or not is_plugin_secret_key(key, contributions):
            continue
        existing = _get_setting(existing_settings, key, _MISSING)
        if existing is _MISSING:
            normalized.pop(key)
        else:
            normalized[key] = existing
    return normalized


def mask_plugin_setting_values(
    values: dict[str, Any],
    contributions: Iterable[Any],
) -> dict[str, Any]:
    """Mask a flat settings-key projection such as a sensor status payload."""
    return {
        key: (MASKED_PLUGIN_SECRET if value else value)
        if is_plugin_secret_key(key, contributions)
        else value
        for key, value in values.items()
    }


def _sensitive_leaf_paths(settings: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in settings.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            paths.update(_sensitive_leaf_paths(value, path))
        elif is_sensitive_log_field(path):
            paths.add(path)
    return paths


def _get_setting(settings: dict[str, Any], key: str, default: Any) -> Any:
    if key in settings:
        return settings[key]
    current: Any = settings
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set_existing_setting(settings: dict[str, Any], key: str, value: Any) -> None:
    if key in settings:
        settings[key] = value
        return
    current: Any = settings
    parts = key.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        current[parts[-1]] = value


__all__ = [
    "MASKED_PLUGIN_SECRET",
    "declared_plugin_secret_keys",
    "is_plugin_secret_key",
    "mask_plugin_setting_values",
    "mask_plugin_settings",
    "normalize_masked_plugin_updates",
]
