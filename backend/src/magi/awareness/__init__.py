"""
Self-Awareness Module

Perceives external world information, supports multiple sources and a five-step perception decision system
"""
from .contracts import SourceEvent
from .source_hub import SourceHub

# New source decoupling contracts (L9)
from .source_base import L2BatchPolicy, Source
from .source_output import (
    ActivityFacet,
    ContentBlock,
    SourceActivity,
    SourceMemoryPolicy,
    SourceNarration,
    SourceOutput,
    SourceOutputMetadata,
)
from .kg_write_queue import (
    KnowledgeGraphEdgeWrite,
    KnowledgeGraphWriteQueue,
    KnowledgeGraphWriteQueueStats,
)
from .source_state import (
    SourceStateStore,
    SourceStateWriteQueue,
    SourceStateWriteQueueStats,
    SqliteSourceStateStore,
)
from .source_sync import PluginRuntimePaths, PullSource, SourceSyncContext, SourceChangeBatch
from .ingestion_gateway import SourceIngestionGateway, SourceIngestionResult
from magi_plugin_sdk import UserContentClearContext, UserContentClearRequest

__all__ = [
    "SourceEvent",
    "SourceHub",
    # New source decoupling contracts
    "ActivityFacet",
    "ContentBlock",
    "L2BatchPolicy",
    "KnowledgeGraphEdgeWrite",
    "KnowledgeGraphWriteQueue",
    "KnowledgeGraphWriteQueueStats",
    "PluginRuntimePaths",
    "PullSource",
    "SourceActivity",
    "Source",
    "SourceIngestionGateway",
    "SourceIngestionResult",
    "SourceMemoryPolicy",
    "SourceNarration",
    "SourceOutput",
    "SourceOutputMetadata",
    "SourceStateStore",
    "SourceStateWriteQueue",
    "SourceStateWriteQueueStats",
    "SourceSyncContext",
    "SourceChangeBatch",
    "SqliteSourceStateStore",
    "UserContentClearContext",
    "UserContentClearRequest",
]
