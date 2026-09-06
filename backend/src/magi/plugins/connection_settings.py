"""Strict connection settings validation shared by API and lifecycle admission."""

from __future__ import annotations

from collections.abc import Iterable
import math
from typing import Any

from magi_plugin_sdk.contracts import ExtensionFieldSpec, PluginPackageState
from magi_plugin_sdk.runtime import PluginConnection

from ..utils.log_redaction import is_sensitive_log_field

_MISSING = object()


def connection_fields(package: PluginPackageState) -> list[ExtensionFieldSpec]:
    """Read only the manifest schema; live contribution fields have no authority."""
    return list(package.manifest.settings_fields)


def _read(settings: dict[str, Any], key: str) -> Any:
    if key in settings:
        return settings[key]
    value: Any = settings
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _leaves(settings: dict[str, Any], prefix: str = "") -> Iterable[tuple[str, Any]]:
    for key, value in settings.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            yield from _leaves(value, path)
        else:
            yield path, value


def validate_connection_settings(connection: PluginConnection, fields: Iterable[ExtensionFieldSpec]) -> None:
    """Validate without coercion; no error includes a submitted value or secret.

    Draft connections may omit required setup fields. Enabling checks required
    active fields, including scoped credential references. Unknown and secret
    setting leaves are rejected even when a caller skips the form renderer.
    """
    schema = {field.key: field for field in fields}
    seen: set[str] = set()
    for key, _ in _leaves(connection.settings):
        if key in seen:
            raise ValueError("Connection settings contain ambiguous duplicate paths")
        seen.add(key)
        if key not in schema:
            raise ValueError("Connection settings contain an undeclared field")
        if schema[key].type == "secret" or is_sensitive_log_field(key):
            raise ValueError("Secret fields must use the scoped credential store")
    for field in schema.values():
        value = _read(connection.settings, field.key)
        if field.type == "secret":
            value = connection.credential_refs.get(field.key, _MISSING)
        active = True
        if field.depends_on_key and field.depends_on_values:
            dependency = _read(connection.settings, field.depends_on_key)
            active = str(dependency).lower() in [item.lower() for item in field.depends_on_values]
        if value is _MISSING:
            if connection.enabled and field.required and active and field.default is None:
                raise ValueError("Required connection configuration is missing")
            continue
        if connection.enabled and active and field.required and value in (None, "", []):
            raise ValueError("Required connection configuration is empty")
        if field.type == "switch":
            valid = isinstance(value, bool)
        elif field.type == "number":
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            if valid:
                valid = (field.minimum is None or value >= field.minimum) and (field.maximum is None or value <= field.maximum)
        elif field.type == "tags" or (field.type == "path" and isinstance(field.default, list)):
            valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
        else:
            valid = isinstance(value, str)
            if valid and field.type == "select":
                valid = value in {option.value for option in field.options} or (not field.required and value == "")
        if not valid:
            raise ValueError("Connection setting type or range does not match its declared field")
