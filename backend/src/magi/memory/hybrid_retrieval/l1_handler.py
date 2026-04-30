"""L1 event memory retrieval handler."""

from __future__ import annotations

from typing import Any, Optional

from .handler_base import RRFSearchHandler
from .l1_execution import L1ExecutionMixin
from .l1_graph_spreading import L1GraphSpreadingMixin
from .l1_paths import L1SearchPathMixin
from .models import RetrievalConfig
from .protocols import L1StoreProtocol


class L1Handler(
    L1ExecutionMixin,
    L1GraphSpreadingMixin,
    L1SearchPathMixin,
    RRFSearchHandler,
):
    """Execute L1 event store queries with triple-path RRF fusion."""

    layer_name = "L1"

    def __init__(
        self,
        l1_store: L1StoreProtocol,
        config: Optional[RetrievalConfig] = None,
        *,
        l2_store: Any = None,
    ) -> None:
        super().__init__(l1_store, config)
        self._l2_store = l2_store

    def with_config(self, config: RetrievalConfig) -> "L1Handler":
        """Return a new L1Handler sharing stores but with *config*."""
        return L1Handler(self._store, config, l2_store=self._l2_store)


__all__ = [
    "L1Handler",
    "L1ExecutionMixin",
    "L1GraphSpreadingMixin",
    "L1SearchPathMixin",
]
