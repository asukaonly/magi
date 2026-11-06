"""Storage-neutral commands for the atomic L1 event boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, List, Dict, Optional, TypedDict, Tuple

from ..event_contracts import MemoryEvent
from .maintenance_contracts import EvidenceAnnotationUpdate, EvidenceBackfillQuery, EventClearState, EventScanItem
from .embedding_contracts import EventChunkRecord, EventEmbeddingPublication, EventEmbeddingSource
from .overview_contracts import EventOverview, EventOverviewQuery
from ..evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope

if TYPE_CHECKING:
    from .source_facets import SourceFacet


from magi_plugin_sdk.storage_models.event_records import (
    EventEvidence,
    EventAppend,
    EventAppendResult,
    EventDeletionPlan,
    EventVisibility,
    MemoryEventRecord,
    EventQuery,
    EventEvidenceReference,
    EventSourceIdentity,
)


from magi_plugin_sdk.storage_ports.events import EventStorageOperations


class MemoryEventRepository(EventStorageOperations, Protocol):
    """The memory domain consumes the complete event persistence contract."""
