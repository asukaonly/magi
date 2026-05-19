"""Lifecycle module that wires the MediaSourceRegistry into bootstrap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.logger import get_logger
from ..bootstrap.lifecycle import LifecycleModule

if TYPE_CHECKING:
    from ..bootstrap.context import RuntimeBootstrapContext

logger = get_logger("magi.media.lifecycle")


class MediaRegistryModule(LifecycleModule):
    """Instantiate MediaSourceRegistry and register built-in source adapters.

    Must run AFTER MemoryStoreModule so unified_memory.l1 is available.
    Plan 2 registers only the photo-library adapter; future sources
    (chat attachments, screen capture) can register here too.
    """

    def __init__(self, context: "RuntimeBootstrapContext") -> None:
        super().__init__(
            name="runtime_media_registry",
            dependencies=("runtime_memory",),
        )
        self._context = context

    async def init(self) -> None:
        from .source_registry import MediaSourceRegistry
        from .adapters.photo_library import PhotoLibraryMediaSource

        unified_memory = getattr(self._context.memory, "unified_memory", None)
        l1_store = getattr(unified_memory, "l1", None) if unified_memory else None
        if l1_store is None:
            logger.warning(
                "MediaRegistryModule setup skipped: unified_memory.l1 unavailable",
            )
            return

        registry = MediaSourceRegistry()
        registry.register(PhotoLibraryMediaSource(l1_store=l1_store))
        self._context.memory.media_source_registry = registry
        logger.info("MediaSourceRegistry initialized with photo-library adapter")

    async def shutdown(self) -> None:
        self._context.memory.media_source_registry = None
