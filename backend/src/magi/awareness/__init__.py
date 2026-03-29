"""
Self-Awareness Module

Perceives external world information, supports multiple sensors and a five-step perception decision system
"""
from .base import Perception, PerceptionType, TriggerMode
from .contracts import ActionEmissionRecord, SensorEvent
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
from .sensor_output import ContentBlock, SensorMemoryPolicy, SensorOutput, SensorOutputMetadata
from .sensor_state import SensorStateStore, SqliteSensorStateStore
from .sensor_sync import PullSyncSensor, SensorSyncContext, SensorSyncResult
from .ingestion_gateway import SensorIngestionGateway, SensorIngestionResult

__all__ = [
    "Perception",
    "PerceptionType",
    "TriggerMode",
    "ActionEmissionRecord",
    "SensorEvent",
    "SensorHub",
    "PerceptionManager",
    "UserMessageSensor",
    "EventSensor",
    "SensordataSensor",
    "TimerSensor",
    # New sensor decoupling contracts
    "ContentBlock",
    "L2BatchPolicy",
    "PullSyncSensor",
    "SensorBase",
    "SensorIngestionGateway",
    "SensorIngestionResult",
    "SensorMemoryPolicy",
    "SensorOutput",
    "SensorOutputMetadata",
    "SensorStateStore",
    "SensorSyncContext",
    "SensorSyncResult",
    "SqliteSensorStateStore",
]
