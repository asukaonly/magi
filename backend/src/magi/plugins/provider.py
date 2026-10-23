"""Container-backed providers for plugin-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..core.container import require_binding

if TYPE_CHECKING:
    from .manager import PluginManager
    from .projections import PluginProjectionService
    from .sources import SourceRegistry




def resolve_plugin_manager() -> "PluginManager":
    """Return the active plugin manager binding."""
    return cast("PluginManager", require_binding("plugin_manager"))


def resolve_plugin_projection_service() -> "PluginProjectionService":
    """Return the active plugin projection service binding."""
    return cast(
        "PluginProjectionService",
        require_binding("plugin_projection_service"),
    )


def resolve_source_registry() -> "SourceRegistry":
    """Return the active source registry binding."""
    return cast("SourceRegistry", require_binding("source_registry"))
