"""Built-in IPC handlers for the Python worker."""

from __future__ import annotations

from typing import Any


async def handle_ping(params: dict[str, Any] | None) -> dict[str, str]:
    """Health-check ping — returns pong."""
    return {"status": "pong"}
