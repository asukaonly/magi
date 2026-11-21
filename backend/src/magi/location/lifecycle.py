"""Location subsystem lifecycle module (L1-tier infrastructure).

Owns construction of the location pipeline — sample store, geocode cache,
Nominatim client, the opt-in IPGeo source, and the read-side ``LocationResolver``
— in ONE place. Exposes them on ``context.location``; consumers read from there:

  * timeline viewport  -> ``context.location.resolver`` (read "where were you")
  * timeline pollers   -> ``context.location.ipgeo_source`` (write opt-in samples)
  * manual-entry API   -> ``location_sample_store`` DI binding (stamp note location)

The stores persist to ``memory.db`` (the ``location_samples`` table lives in the
``memory_shared`` migration chain), so this module depends on
``runtime_database_migrations`` and reads the path from ``runtime_paths`` directly
— it does NOT need ``UnifiedMemoryStore``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from dependency_injector import providers

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.container import get_container
from ..core.logger import get_logger
from .nominatim import NominatimClient
from .resolver import LocationResolver
from .sources.ipgeo import IPGeoLocationSource
from .store import LocationSampleStore, PlaceGeocodeCache

logger = get_logger(__name__)


class LocationModule(LifecycleModule):
    """Build and expose the location subsystem (L1 infrastructure)."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        proxy_url_resolver: Optional[Callable[[], Optional[str]]] = None,
    ):
        super().__init__(
            name="runtime_location",
            dependencies=("runtime_database_migrations",),
        )
        self._context = context
        self._proxy_url_resolver = proxy_url_resolver

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        db_path = str(runtime_paths.memory_db_path)

        sample_store = LocationSampleStore(db_path=db_path)
        geocode_cache = PlaceGeocodeCache(db_path=db_path)
        _ = NominatimClient(cache=geocode_cache, proxy_url_resolver=self._proxy_url_resolver)
        ipgeo_source = IPGeoLocationSource(
            store=sample_store,
            proxy_url_resolver=self._proxy_url_resolver,
        )
        resolver = LocationResolver(sources=[ipgeo_source])

        loc = self._context.location
        loc.sample_store = sample_store
        loc.geocode_cache = geocode_cache
        loc.resolver = resolver
        loc.ipgeo_source = ipgeo_source

        # DI binding for consumers outside the bootstrap context (API routers).
        get_container().location_sample_store.override(providers.Object(sample_store))
        logger.info("Location subsystem initialized (resolver + opt-in IPGeo source)")

    async def shutdown(self) -> None:
        try:
            get_container().location_sample_store.reset_override()
        except Exception:
            pass
        loc = self._context.location
        loc.sample_store = None
        loc.geocode_cache = None
        loc.resolver = None
        loc.ipgeo_source = None


__all__ = ["LocationModule"]
