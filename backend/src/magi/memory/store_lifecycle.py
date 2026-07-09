"""Lifecycle helpers for the unified memory store."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class UnifiedMemoryLifecycleMixin:
    """Initialize and shut down enabled L0-L4 stores."""

    l0: Any
    l1: Any
    l2: Any
    l2_entity_catalog: Any
    l2_pipeline: Any
    l3: Any
    l4: Any
    _edge_embedding_drainer: Any
    _edge_embedding_worker: Any
    _portrait_projection_scheduler: Any
    _initialized: bool

    async def initialize(self) -> None:
        """Initialize enabled stores."""
        if self._initialized:
            return

        for store in (self.l0, self.l1, self.l2, self.l2_entity_catalog, self.l3, self.l4):
            if store is None:
                continue
            await store.initialize()
        if self.l2_pipeline is not None:
            await self.l2_pipeline.start()

        # Start the L2 edge-embedding drain only when vectors are enabled.
        if (
            self._edge_embedding_worker is not None
            and self.l2_entity_catalog is not None
            and self.l2_entity_catalog.embedding_service is not None
        ):
            await self._edge_embedding_worker.start()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def shutdown(self) -> None:
        """Drain asynchronous workers and close store resources."""
        if self.l2_pipeline is not None:
            await self.l2_pipeline.shutdown()
        if self._portrait_projection_scheduler is not None:
            await self._portrait_projection_scheduler.shutdown()
        if self._edge_embedding_worker is not None:
            await self._edge_embedding_worker.stop()
        for store in (self.l1, self.l3, self.l4):
            if store is None or not hasattr(store, "shutdown"):
                continue
            await store.shutdown()


__all__ = ["UnifiedMemoryLifecycleMixin"]
