"""Host-platform tool selection helpers."""

from __future__ import annotations

import os


def native_shell_tool_name(os_name: str | None = None) -> str:
    """Return the only shell tool that should be exposed on this host."""
    return "powershell" if (os_name or os.name) == "nt" else "bash"


__all__ = ["native_shell_tool_name"]
