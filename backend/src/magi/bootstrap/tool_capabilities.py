"""Composition-root assembly of tool capability ports.

Lives in bootstrap/ (outside the numbered layer stack) because it wires
adapters over services from many layers — that is composition, not domain
logic. Per-cluster adapters are added in later tasks; until then the bundle
is empty (all ports None).
"""
from __future__ import annotations

from magi_plugin_sdk.capabilities import ToolCapabilities

_capabilities: ToolCapabilities | None = None


def build_tool_capabilities() -> ToolCapabilities:
    """Return the process-wide tool-capabilities bundle (built once)."""
    global _capabilities
    if _capabilities is None:
        _capabilities = ToolCapabilities()
    return _capabilities


def reset_tool_capabilities() -> None:
    """Drop the cached bundle so the next build re-assembles it (tests only)."""
    global _capabilities
    _capabilities = None
