"""
Self-Awareness Module

Perceives external world information, supports multiple sensors and a five-step perception decision system
"""
from .base import Perception, PerceptionType, TriggerMode
from .contracts import SensorEvent
from .manager import PerceptionManager
from .sensor_hub import SensorHub
from .sensors import (
    UserMessageSensor,
    EventSensor,
    SensordataSensor,
    TimerSensor,
)

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
from .sensor_state import SensorStateStore, SqliteSensorStateStore
from .sensor_sync import PluginRuntimePaths, PullSyncSensor, SensorSyncContext, SensorSyncResult
from .ingestion_gateway import SensorIngestionGateway, SensorIngestionResult

__all__ = [
    "Perception",
    "PerceptionType",
    "TriggerMode",
    "SensorEvent",
    "SensorHub",
    "PerceptionManager",
    "UserMessageSensor",
    "EventSensor",
    "SensordataSensor",
    "TimerSensor",
    # New sensor decoupling contracts
    "ActivityFacet",
    "ContentBlock",
    "L2BatchPolicy",
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
    "SensorSyncContext",
    "SensorSyncResult",
    "SqliteSensorStateStore",
]
