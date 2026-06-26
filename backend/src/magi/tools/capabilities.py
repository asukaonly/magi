"""Runtime access point for tool capability ports.

The composition root assembles the concrete host adapters and registers a
provider here. Runtime packages depend on this narrow tools-layer entry point
instead of importing bootstrap assembly code directly.
"""

from __future__ import annotations

from collections.abc import Callable

from magi_plugin_sdk.capabilities import ToolCapabilities


ToolCapabilitiesProvider = Callable[[], ToolCapabilities]

_provider: ToolCapabilitiesProvider = ToolCapabilities


def configure_tool_capabilities_provider(provider: ToolCapabilitiesProvider) -> None:
    """Register the process-wide tool capabilities provider."""
    global _provider
    _provider = provider


def build_tool_capabilities() -> ToolCapabilities:
    """Return the process-wide tool capabilities bundle."""
    return _provider()


def reset_tool_capabilities_provider() -> None:
    """Restore the SDK-only default provider; intended for shutdown and tests."""
    global _provider
    _provider = ToolCapabilities
