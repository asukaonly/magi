"""Shared helpers for the system-settings tool."""

from __future__ import annotations

from typing import Any


SENSITIVE_PATTERNS = [
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "private",
]

READ_ONLY_FIELDS = [
    "config_path",
    "version",
]


def _is_sensitive_field(field_path: str) -> bool:
    """Check if a field path contains sensitive information."""
    field_lower = field_path.lower()
    return any(pattern in field_lower for pattern in SENSITIVE_PATTERNS)


def _is_read_only_field(field_path: str) -> bool:
    """Check if a field is read-only."""
    field_lower = field_path.lower()
    return any(pattern in field_lower for pattern in READ_ONLY_FIELDS)


def _get_nested_value(obj: Any, path: str) -> tuple[bool, Any, str]:
    """Get a nested value using dot notation."""
    parts = path.split(".")
    current = obj

    for part in parts:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None, f"Field '{part}' not found in path '{path}'"

    return True, current, ""


def _serialize_value(value: Any, mask_secrets: bool = True) -> Any:
    """Serialize a value for output, masking sensitive data."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [_serialize_value(item, mask_secrets) for item in value]

    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if mask_secrets and _is_sensitive_field(k):
                result[k] = "***MASKED***"
            else:
                result[k] = _serialize_value(v, mask_secrets)
        return result

    if hasattr(value, "model_dump"):
        return _serialize_value(value.model_dump(), mask_secrets)

    if hasattr(value, "__dict__"):
        return _serialize_value(value.__dict__, mask_secrets)

    return str(value)


__all__ = [
    "READ_ONLY_FIELDS",
    "SENSITIVE_PATTERNS",
    "_get_nested_value",
    "_is_read_only_field",
    "_is_sensitive_field",
    "_serialize_value",
]
