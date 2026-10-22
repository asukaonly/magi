"""Container-backed provider for the location subsystem.

Mirrors ``memory/provider.py``: the binding is overridden at bootstrap by
``LocationModule`` (``location/lifecycle.py``); consumers that live outside the
bootstrap context (e.g. API routers) resolve it through these accessors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ..core.container import require_binding

if TYPE_CHECKING:
    from .store import LocationSampleStore




def get_location_sample_store() -> "LocationSampleStore":
    """Return the active location sample-store binding."""
    return cast("LocationSampleStore", require_binding("location_sample_store"))


__all__ = ["get_location_sample_store"]
