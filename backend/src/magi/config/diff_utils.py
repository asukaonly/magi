"""Dictionary merge/diff helpers for sparse config persistence."""

from __future__ import annotations

from typing import Any, Dict


_UNSET = object()


def deep_merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep-merged dict where override values win."""
    merged: Dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = deep_merge_dict(value, {})
        else:
            merged[key] = value

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], value)
        elif isinstance(value, dict):
            merged[key] = deep_merge_dict({}, value)
        else:
            merged[key] = value
    return merged


def extract_dict_overrides(defaults: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Return nested overrides where current differs from defaults."""
    result = _extract_override_value(defaults, current)
    if isinstance(result, dict):
        return result
    return {}


def _extract_override_value(default_value: Any, current_value: Any) -> Any:
    if isinstance(default_value, dict) and isinstance(current_value, dict):
        diff: Dict[str, Any] = {}
        for key, value in current_value.items():
            if key not in default_value:
                diff[key] = value
                continue
            nested = _extract_override_value(default_value[key], value)
            if nested is _UNSET:
                continue
            diff[key] = nested
        if not diff:
            return _UNSET
        return diff

    if current_value == default_value:
        return _UNSET
    return current_value
