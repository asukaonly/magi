"""User-level magi config root for code_agent.

Mirrors ``magi.utils.runtime.get_default_chat_workspace_path``: ``~/.magi/``.
Override via env ``MAGI_HOME`` for tests.
"""
from __future__ import annotations

import os
from pathlib import Path


def magi_user_root() -> Path:
    override = os.environ.get("MAGI_HOME")
    base = Path(override).expanduser() if override else Path.home() / ".magi"
    base.mkdir(parents=True, exist_ok=True)
    return base


def code_agent_settings_path() -> Path:
    return magi_user_root() / "code_agent.toml"


def code_agent_probe_cache_path() -> Path:
    return magi_user_root() / "code_agent_probe.json"
