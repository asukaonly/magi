"""Managed chat workspace helpers."""

from __future__ import annotations

from pathlib import Path


DEFAULT_CHAT_WORKSPACE_DIRNAME = "chat-workspace"


def get_default_chat_workspace_path() -> str:
    """Return the managed default workspace path for desktop chat sessions."""
    workspace_path = (Path.home() / ".magi" / DEFAULT_CHAT_WORKSPACE_DIRNAME).expanduser()
    workspace_path.mkdir(parents=True, exist_ok=True)
    return str(workspace_path.resolve())
