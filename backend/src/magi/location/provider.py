"""Container-backed provider for the location subsystem.

Mirrors ``memory/provider.py``: the binding is overridden at bootstrap by
``LocationModule`` (``location/lifecycle.py``); consumers that live outside the
bootstrap context (e.g. API routers) resolve it through these accessors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from .store import LocationSampleStore


def _require_location_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def get_location_sample_store() -> "LocationSampleStore":
    """Return the active location sample-store binding."""
    return cast("LocationSampleStore", _require_location_binding("location_sample_store"))


__all__ = ["get_location_sample_store"]
