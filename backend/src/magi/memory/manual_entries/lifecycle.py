"""Manual-entries lifecycle module.

Builds the user-authored manual-entry subsystem — the entry store, the asset
store, and the weather fetcher — and exposes it via ``context.manual_entries``
plus DI bindings for the API router. Previously these were built inside
``UnifiedMemoryStore.__init__`` and fished off it via ``getattr`` (a
service-locator pattern); memory had no reason to construct them.

Manual entries are a timeline-surface feature (added and rendered on the
timeline page). ``ManualEntryL1Projector`` mirrors entries into the L1 event
stream, while the API asks ``UnifiedMemoryStore`` to govern an old projection
before replacing or deleting it. This module owns just the store/asset/weather
construction; it reads the memory.db path + media dir from ``runtime_paths``
directly and does not construct ``UnifiedMemoryStore``.
"""

from __future__ import annotations

from dependency_injector import providers

from ...bootstrap.context import RuntimeBootstrapContext, require_initialized
from ...bootstrap.lifecycle import LifecycleModule
from ...core.container import get_container
from ...core.logger import get_logger
from .asset_store import ManualEntryAssetStore
from .l1_projector import ManualEntryL1Projector
from .recovery import ManualEntryRecoveryService
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
            dependencies=("runtime_database_migrations", "runtime_memory"),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        store = ManualEntryStore(db_path=str(runtime_paths.memory_db_path))
        asset_store = ManualEntryAssetStore(media_root=runtime_paths.memory_dir.parent / "media")
        weather_fetcher = WeatherFetcher()
        projector = (
            ManualEntryL1Projector(memory=memory)
            if getattr(memory, "l1", None) is not None
            else None
        )
        recovery_service = ManualEntryRecoveryService(
            store=store,
            projector=projector,
            memory=memory,
        )

        slot = self._context.manual_entries
        slot.store = store
        slot.asset_store = asset_store
        slot.weather_fetcher = weather_fetcher
        slot.recovery_service = recovery_service

        container = get_container()
        container.manual_entry_store.override(providers.Object(store))
        container.manual_entry_asset_store.override(providers.Object(asset_store))
        container.manual_entry_weather_fetcher.override(providers.Object(weather_fetcher))
        recovery_stats = await recovery_service.start()
        logger.info(
            "Manual-entries subsystem initialized",
            recovery=recovery_stats.to_dict(),
        )

    async def shutdown(self) -> None:
        slot = self._context.manual_entries
        if slot.recovery_service is not None:
            await slot.recovery_service.stop()
        container = get_container()
        for name in _BINDINGS:
            try:
                getattr(container, name).reset_override()
            except Exception:
                pass
        slot.store = None
        slot.asset_store = None
        slot.weather_fetcher = None
        slot.recovery_service = None


__all__ = ["ManualEntriesModule"]
