"""Location subsystem lifecycle module (L1-tier infrastructure).

Owns construction of the location pipeline — sample store, geocode cache,
Nominatim client, the WiFi/IPGeo sources, and the read-side ``LocationResolver``
— in ONE place. Previously these were built inside ``UnifiedMemoryStore.__init__``
(memory had no domain stake in location) and the WiFi/IPGeo sources were built a
*second* time inside the timeline scheduler module. This module builds them once
and exposes them on ``context.location``; consumers read from there:

  * timeline viewport  -> ``context.location.resolver`` (read "where were you")
  * timeline pollers   -> ``context.location.{ipgeo,wifi}_source`` (write samples)
  * manual-entry API   -> ``location_sample_store`` DI binding (stamp note location)

The stores persist to ``memory.db`` (the ``location_samples`` table lives in the
``memory_shared`` migration chain), so this module depends on
``runtime_database_migrations`` and reads the path from ``runtime_paths`` directly
— it does NOT need ``UnifiedMemoryStore``.
"""

from __future__ import annotations

from dependency_injector import providers

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.container import get_container
from ..core.logger import get_logger
from .nominatim import NominatimClient
from .resolver import LocationResolver
from .sources.ipgeo import IPGeoLocationSource
from .sources.wifi import WiFiLocationSource
from .store import LocationSampleStore, PlaceGeocodeCache

logger = get_logger(__name__)


class LocationModule(LifecycleModule):
    """Build and expose the location subsystem (L1 infrastructure)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_location",
            dependencies=("runtime_database_migrations",),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        db_path = str(runtime_paths.memory_db_path)

        sample_store = LocationSampleStore(db_path=db_path)
        geocode_cache = PlaceGeocodeCache(db_path=db_path)
        nominatim = NominatimClient(cache=geocode_cache)
        wifi_source = WiFiLocationSource(store=sample_store, nominatim=nominatim)
        ipgeo_source = IPGeoLocationSource(store=sample_store)
        resolver = LocationResolver(sources=[wifi_source, ipgeo_source])

        loc = self._context.location
        loc.sample_store = sample_store
        loc.geocode_cache = geocode_cache
        loc.resolver = resolver
        loc.wifi_source = wifi_source
        loc.ipgeo_source = ipgeo_source

        # DI binding for consumers outside the bootstrap context (API routers).
        get_container().location_sample_store.override(providers.Object(sample_store))
        logger.info("Location subsystem initialized (resolver + WiFi/IPGeo sources)")

    async def shutdown(self) -> None:
        try:
            get_container().location_sample_store.reset_override()
        except Exception:
            pass
        loc = self._context.location
        loc.sample_store = None
        loc.geocode_cache = None
        loc.resolver = None
        loc.wifi_source = None
        loc.ipgeo_source = None


__all__ = ["LocationModule"]
