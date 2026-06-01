"""Container-backed provider for the control-plane permission gateway."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.container import get_container

if TYPE_CHECKING:
    from .gateway import PermissionGateway


def get_permission_gateway() -> "PermissionGateway":
    """Return the active permission gateway binding."""
    provider = get_container().permission_gateway
    instance = provider()
    if instance is None:
        raise RuntimeError("permission_gateway binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError("permission_gateway binding is not initialized")
    return instance
