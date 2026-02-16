"""
event system - event data structure definition
"""
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from time import time
import uuid


class EventLevel(IntEnum):
    """
    event level (affects priority and persistence strategy)

    0: DEBUG     - Debug info
    1: INFO      - Normal info
    2: WARNING   - Warning
    3: ERROR     - Error
    4: CRITICAL  - Critical error
    5: EMERGENCY - Emergency event (highest priority)
    """
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4
    EMERGENCY = 5


class PropagationMode:
    """event propagation pattern"""
    BROADCAST = "broadcast"  # broadcast: all subscribers receive
    COMPETING = "competing"  # competing: only one subscriber receives


@dataclass
class Event:
    """
    eventdatastructure

    Attributes:
        type: eventtype（如 "AgentStarted", "PerceptionReceived"）
        data: eventdata（可以isanytype）
        timestamp: timestamp
        source: event source (can be agent id, module name, etc.)
        level: event level (affects priority and persistence strategy)
        correlation_id: correlation id (for tracking event chain)
        metadata: additional metadata
    """
    type: str
    data: Any
    timestamp: float = field(default_factory=time)
    source: str = "unknown"
    level: EventLevel = EventLevel.INFO
    correlation_id: Optional[str] = field(default=None)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """process after initialization"""
        if self.correlation_id is None:
            # generation唯一的associateid
            self.correlation_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """convert为dictionary"""
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "level": self.level.value,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """从dictionarycreateevent"""
        return cls(
            type=data["type"],
            data=data["data"],
            timestamp=data.get("timestamp", time()),
            source=data.get("source", "unknown"),
            level=EventLevel(data.get("level", EventLevel.INFO)),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
        )


# coreeventtype定义
class EventTypes:
    """coreeventtypeConstant"""

    # 生命periodevent
    AGENT_STARTED = "AgentStarted"
    AGENT_STOPPED = "AgentStopped"
    STATE_CHANGED = "StateChanged"

    # Perceptionevent
    PERCEPTION_RECEIVED = "PerceptionReceived"
    PERCEPTION_PROCESSED = "Perceptionprocessed"

    # processevent
    ACTION_EXECUTED = "ActionExecuted"
    CAPABILITY_CREATED = "CapabilityCreated"
    CAPABILITY_UPDATED = "CapabilityUpdated"

    # learningevent
    EXPERIENCE_STORED = "ExperienceStored"

    # errorevent
    ERROR_OCCURRED = "errorOccurred"
    HANDLER_FAILED = "HandlerFailed"

    # 循环event
    LOOP_STARTED = "LoopStarted"
    LOOP_COMPLETED = "LoopCompleted"
    LOOP_PAUSED = "LoopPaused"
    LOOP_RESUMED = "LoopResumed"
    LOOP_PHASE_STARTED = "LoopPhaseStarted"
    LOOP_PHASE_COMPLETED = "LoopPhaseCompleted"

    # 健康event
    HEALTH_WARNING = "HealthWarning"

    # 任务event
    TASK_CREATED = "TaskCreated"
    TASK_ASSIGNED = "TaskAssigned"
    TASK_STARTED = "TaskStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"

    # User messageevent
    USER_MESSAGE = "UserMessage"


# 业务eventtypeConstant（L1 层storage使用）
class BusinessEventTypes:
    """
    业务eventtypeConstant

    这些is经过filterandconvert后的业务event，
    用于 L1 层storage，专注于userrow为analysis。
    """

    # userInputevent（来自 USER_MESSAGE）
    USER_INPUT = "USER_INPUT"

    # AI responseevent（来自 ACTION_EXECUTED，当 action_type=ChatResponseAction）
    AI_RESPONSE = "AI_RESPONSE"

    # tool调用event（来自 ACTION_EXECUTED，当 action_type istool调用）
    TOOL_INVOKED = "TOOL_INVOKED"

    # 系统Exceptionevent（只recordcritical error，level >= error）
    SYSTEM_ERROR = "SYSTEM_ERROR"
