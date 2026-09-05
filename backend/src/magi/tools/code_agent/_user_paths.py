"""User-level magi config root for code_agent.

Mirrors ``magi.utils.runtime.get_default_chat_workspace_path``: ``~/.magi/``.
The desktop host, gateway, backend and SDK share ``MAGI_HOME``.
"""
from __future__ import annotations

from magi_plugin_sdk.runtime_paths import get_magi_home
from pathlib import Path


def magi_user_root() -> Path:
    base = get_magi_home()
    base.mkdir(parents=True, exist_ok=True)
    return base


def code_agent_settings_path() -> Path:
    return magi_user_root() / "code_agent.toml"


def code_agent_probe_cache_path() -> Path:
    return magi_user_root() / "code_agent_probe.json"
