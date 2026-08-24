"""Write user-level and project-level code_agent settings TOML files.

All writes are atomic (tempfile + os.replace via
``magi_plugin_sdk.fs.atomic_write_text``). Patches are
deep-merged into the existing TOML so partial PATCH calls from the API
don't clobber unrelated keys.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import tomli_w

from magi_plugin_sdk.fs import atomic_write_text
from ._user_paths import code_agent_settings_path


def _load_toml_text(text: str) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib
        return tomllib.loads(text)
    import tomli
    return tomli.loads(text)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return _load_toml_text(path.read_text(encoding="utf-8"))


def _write_toml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = tomli_w.dumps(payload)
    atomic_write_text(path, serialized)


def write_user_settings(patch: dict[str, Any]) -> Path:
    """Deep-merge ``patch`` into ``~/.magi/code_agent.toml``."""
    target = code_agent_settings_path()
    merged = _deep_merge(_read_optional(target), patch)
    _write_toml(target, merged)
    return target


def _project_path(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / ".magi" / "code_agent.toml"


def write_project_settings(workspace_root: Path | str, patch: dict[str, Any]) -> Path:
    """Deep-merge ``patch`` into ``<workspace>/.magi/code_agent.toml``."""
    target = _project_path(workspace_root)
    merged = _deep_merge(_read_optional(target), patch)
    _write_toml(target, merged)
    return target


def reset_project_settings(workspace_root: Path | str) -> None:
    """Remove the project-level toml; no-op when missing."""
    target = _project_path(workspace_root)
    if target.is_file():
        target.unlink()


__all__ = [
    "reset_project_settings",
    "write_project_settings",
    "write_user_settings",
]
