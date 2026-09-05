"""
Self-Awareness Module

Perceives external world information, supports multiple sensors and a five-step perception decision system
"""
from .contracts import SensorEvent
from .sensor_hub import SensorHub

# New sensor decoupling contracts (L9)
from .sensor_base import L2BatchPolicy, SensorBase
from .sensor_output import (
    ActivityFacet,
    ContentBlock,
    SensorActivity,
    SensorMemoryPolicy,
    SensorNarration,
    SensorOutput,
    SensorOutputMetadata,
)
from .kg_write_queue import (
    KnowledgeGraphEdgeWrite,
    KnowledgeGraphWriteQueue,
    KnowledgeGraphWriteQueueStats,
)
from .sensor_state import (
    SensorStateStore,
    SensorStateWriteQueue,
    SensorStateWriteQueueStats,
    SqliteSensorStateStore,
)
from .sensor_sync import PluginRuntimePaths, PullSyncSensor, SensorSyncContext, SourceChangeBatch
from .ingestion_gateway import SensorIngestionGateway, SensorIngestionResult
from magi_plugin_sdk import UserContentClearContext, UserContentClearRequest

__all__ = [
    "SensorEvent",
    "SensorHub",
    # New sensor decoupling contracts
    "ActivityFacet",
    "ContentBlock",
    "L2BatchPolicy",
    "KnowledgeGraphEdgeWrite",
    "KnowledgeGraphWriteQueue",
    "KnowledgeGraphWriteQueueStats",
    "PluginRuntimePaths",
    "PullSyncSensor",
    "SensorActivity",
    "SensorBase",
    "SensorIngestionGateway",
    "SensorIngestionResult",
    "SensorMemoryPolicy",
    "SensorNarration",
    "SensorOutput",
    "SensorOutputMetadata",
    "SensorStateStore",
    "SensorStateWriteQueue",
    "SensorStateWriteQueueStats",
    "SensorSyncContext",
    "SourceChangeBatch",
    "SqliteSensorStateStore",
    "UserContentClearContext",
    "UserContentClearRequest",
]
