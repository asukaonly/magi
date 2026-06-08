"""Manual-entries lifecycle module.

Builds the user-authored manual-entry subsystem — the entry store, the asset
store, and the weather fetcher — and exposes it via ``context.manual_entries``
plus DI bindings for the API router. Previously these were built inside
``UnifiedMemoryStore.__init__`` and fished off it via ``getattr`` (a
service-locator pattern); memory had no reason to construct them.

Manual entries are a timeline-surface feature (added and rendered on the
timeline page). Memory's only legitimate stake is the L1 *projection* — the
``ManualEntryL1Projector`` still mirrors entries into the L1 event stream, built
from the memory-owned L1 store at the API boundary. This module owns just the
store/asset/weather construction; it reads the memory.db path + media dir from
``runtime_paths`` directly and does not need ``UnifiedMemoryStore``.
"""

from __future__ import annotations

from dependency_injector import providers

from ...bootstrap.context import RuntimeBootstrapContext, require_initialized
from ...bootstrap.lifecycle import LifecycleModule
from ...core.container import get_container
from ...core.logger import get_logger
from .asset_store import ManualEntryAssetStore
from .store import ManualEntryStore
from .weather_fetcher import WeatherFetcher

logger = get_logger(__name__)

_BINDINGS = (
    "manual_entry_store",
    "manual_entry_asset_store",
    "manual_entry_weather_fetcher",
)


class ManualEntriesModule(LifecycleModule):
    """Build and expose the manual-entry subsystem (store/asset/weather)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_manual_entries",
            dependencies=("runtime_database_migrations",),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        store = ManualEntryStore(db_path=str(runtime_paths.memory_db_path))
        asset_store = ManualEntryAssetStore(media_root=runtime_paths.memory_dir.parent / "media")
        weather_fetcher = WeatherFetcher()

        slot = self._context.manual_entries
        slot.store = store
        slot.asset_store = asset_store
        slot.weather_fetcher = weather_fetcher

        container = get_container()
        container.manual_entry_store.override(providers.Object(store))
        container.manual_entry_asset_store.override(providers.Object(asset_store))
        container.manual_entry_weather_fetcher.override(providers.Object(weather_fetcher))
        logger.info("Manual-entries subsystem initialized (store + assets + weather)")

    async def shutdown(self) -> None:
        container = get_container()
        for name in _BINDINGS:
            try:
                getattr(container, name).reset_override()
            except Exception:
                pass
        slot = self._context.manual_entries
        slot.store = None
        slot.asset_store = None
        slot.weather_fetcher = None


__all__ = ["ManualEntriesModule"]
