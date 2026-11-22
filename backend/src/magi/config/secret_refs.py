"""Helpers for storing config secret fields as OS secret-store references."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from ..core.secret_store import (
    SecretStore,
    is_secret_ref,
    make_secret_ref,
)

_SECRET_LEAF_KEYS = frozenset(
    {
        "api_key",
        "password",
        "bot_token",
        "client_secret",
        "access_token",
        "secret",
    }
)


def _lookup_path(data: Any, path: tuple[str, ...]) -> Any:
    cursor = data
    for segment in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(segment)
    return cursor


def _set_path(data: Dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor: Dict[str, Any] = data
    for segment in path[:-1]:
        nxt = cursor.get(segment)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[segment] = nxt
        cursor = nxt
    cursor[path[-1]] = value


def find_plaintext_secrets(
    data: Dict[str, Any],
    *,
    namespace: str,
) -> list[tuple[tuple[str, ...], str, str]]:
    """Return ``(path_tuple, secret_ref, plaintext)`` for all non-empty plaintext secrets."""
    found: list[tuple[tuple[str, ...], str, str]] = []

    def _walk(node: Any, prefix: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            key_str = str(key)
            current_path = (*prefix, key_str)
            if isinstance(value, dict):
                _walk(value, current_path)
            elif key_str in _SECRET_LEAF_KEYS and isinstance(value, str):
                if value and not is_secret_ref(value):
                    ref = make_secret_ref(namespace, *current_path)
                    found.append((current_path, ref, value))

    _walk(data, ())
    return found


def find_cleared_secret_refs(
    data: Dict[str, Any],
    previous_disk_data: Dict[str, Any] | None,
) -> list[str]:
    """Return refs that existed on disk previously and were cleared in ``data``."""
    if not isinstance(previous_disk_data, dict):
        return []
    cleared: list[str] = []

    def _walk(prev_node: Any, prefix: tuple[str, ...]) -> None:
        if not isinstance(prev_node, dict):
            return
        for key, prev_val in prev_node.items():
            key_str = str(key)
            current_path = (*prefix, key_str)
            if isinstance(prev_val, dict):
                _walk(prev_val, current_path)
            elif key_str in _SECRET_LEAF_KEYS and is_secret_ref(prev_val):
                new_val = _lookup_path(data, current_path)
                if new_val is None or new_val == "":
                    cleared.append(str(prev_val))

    _walk(previous_disk_data, ())
    return cleared


def externalize_yaml_secrets(
    data: Dict[str, Any],
    *,
    namespace: str,
    secret_store: SecretStore,
    previous_disk_data: Dict[str, Any] | None = None,
) -> tuple[Dict[str, Any], list[tuple[str, str | None]], list[str]]:
    """Replace plaintext secrets with ``secret_ref:...`` and write them to ``secret_store``.

    Returns ``(sanitized_copy, rollback_entries, cleared_refs)``. If writing any
    secret fails, previously written secrets in this batch are rolled back before
    re-raising.
    """
    sanitized = deepcopy(data)
    entries = find_plaintext_secrets(sanitized, namespace=namespace)
    rollback: list[tuple[str, str | None]] = []
    try:
        for path, ref, plaintext in entries:
            previous_secret = secret_store.get(ref)
            secret_store.set(ref, plaintext)
            rollback.append((ref, previous_secret))
            _set_path(sanitized, path, ref)
    except Exception:
        rollback_secret_writes(secret_store, rollback)
        raise

    cleared_refs = find_cleared_secret_refs(sanitized, previous_disk_data)
    return sanitized, rollback, cleared_refs


def rollback_secret_writes(
    secret_store: SecretStore,
    rollback_entries: list[tuple[str, str | None]],
) -> None:
    """Best-effort restore of previous secret-store state after a failed save or migration."""
    for ref, previous_value in reversed(rollback_entries):
        try:
            if previous_value is None:
                secret_store.delete(ref)
            else:
                secret_store.set(ref, previous_value)
        except Exception:
            pass


def hydrate_yaml_secrets(
    data: Dict[str, Any],
    *,
    secret_store: SecretStore,
) -> Dict[str, Any]:
    """Resolve all ``secret_ref:...`` placeholders in a config dict in memory."""
    hydrated = deepcopy(data)

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if isinstance(value, dict):
                    _walk(value)
                elif isinstance(value, list):
                    for item in value:
                        _walk(item)
                elif is_secret_ref(value):
                    resolved = secret_store.get(value)
                    node[key] = resolved if resolved is not None else ""
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(hydrated)
    return hydrated


__all__ = [
    "externalize_yaml_secrets",
    "find_cleared_secret_refs",
    "find_plaintext_secrets",
    "hydrate_yaml_secrets",
    "rollback_secret_writes",
]
