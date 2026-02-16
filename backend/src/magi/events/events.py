"""
event system - event data structure definition
"""
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from time import time
import uuid


class eventlevel(IntEnum):
    """
    event level (affects priority and persistence strategy)

    0: debug     - Debuginfo
    1: INFO      - notttrmal info
    2: warnING   - Warning
    3: error     - error
    4: CRITICAL  - critical error
    5: EMERGENCY - emergency event (highest priority)
    """
    debug = 0
    INFO = 1
    warnING = 2
    error = 3
    CRITICAL = 4
    EMERGENCY = 5


class propagationMode:
    """event propagation pattern"""
    BROADCasT = "broadcast"  # broadcast: all subscribers receive
    COMPETING = "competing"  # competing: only one subscriber receives


@dataclass
class event:
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
    level: eventlevel = EventLevel.INFO
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
    def from_dict(cls, data: Dict[str, Any]) -> "event":
        """从dictionarycreateevent"""
        return cls(
            type=data["type"],
            data=data["data"],
            timestamp=data.get("timestamp", time()),
            source=data.get("source", "unknown"),
            level=eventlevel(data.get("level", EventLevel.INFO)),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
        )


# coreeventtype定义
class eventtypes:
    """coreeventtypeConstant"""

    # 生命periodevent
    AGENT_startED = "AgentStarted"
    AGENT_stopPED = "AgentStopped"
    STATE_CHANGED = "StateChanged"

    # Perceptionevent
    PERCEPTION_receiveD = "PerceptionReceived"
    PERCEPTION_processED = "Perceptionprocessed"

    # processevent
    ACTION_executeD = "ActionExecuted"
    CAPABILITY_createD = "CapabilityCreated"
    CAPABILITY_updateD = "CapabilityUpdated"

    # learningevent
    EXPERIENCE_STORED = "ExperienceStored"

    # errorevent
    error_OCCURRED = "errorOccurred"
    handler_failED = "HandlerFailed"

    # 循环event
    LOOP_startED = "LoopStarted"
    LOOP_COMPLETED = "LoopCompleted"
    LOOP_pauseD = "LoopPaused"
    LOOP_resumeD = "LoopResumed"
    LOOP_PHasE_startED = "LoopPhaseStarted"
    LOOP_PHasE_COMPLETED = "LoopPhaseCompleted"

    # 健康event
    HEALTH_warnING = "HealthWarning"

    # 任务event
    task_createD = "TaskCreated"
    task_assignED = "TaskAssigned"
    task_startED = "TaskStarted"
    task_COMPLETED = "TaskCompleted"
    task_failED = "TaskFailed"

    # User messageevent
    user_MESSAGE = "UserMessage"


# 业务eventtypeConstant（L1 层storage使用）
class Businesseventtypes:
    """
    业务eventtypeConstant

    这些is经过filterandconvert后的业务event，
    用于 L1 层storage，专注于userrow为analysis。
    """

    # userInputevent（来自 user_MESSAGE）
    user_input = "user_input"

    # AI responseevent（来自 ACTION_executeD，当 action_type=ChatResponseAction）
    AI_RESPONSE = "AI_RESPONSE"

    # tool调用event（来自 ACTION_executeD，当 action_type istool调用）
    TOOL_INVOKED = "TOOL_INVOKED"

    # 系统Exceptionevent（只recordcritical error，level >= error）
    system_error = "system_error"
