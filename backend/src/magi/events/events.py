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
    Event data structure

    Attributes:
        type: event type (e.g. "AgentStarted", "PerceptionReceived")
        data: event data (can be any type)
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
        """Post-initialization processing"""
        if self.correlation_id is None:
            # Generate unique correlation id
            self.correlation_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
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
        """Create event from dictionary"""
        return cls(
            type=data["type"],
            data=data["data"],
            timestamp=data.get("timestamp", time()),
            source=data.get("source", "unknown"),
            level=EventLevel(data.get("level", EventLevel.INFO)),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
        )


# Core event type definitions
class EventTypes:
    """Core event type constants"""

    # Lifecycle events
    AGENT_STARTED = "AgentStarted"
    AGENT_STOPPED = "AgentStopped"
    STATE_CHANGED = "StateChanged"

    # Perception events
    PERCEPTION_RECEIVED = "PerceptionReceived"
    PERCEPTION_PROCESSED = "Perceptionprocessed"

    # Processing events
    ACTION_EXECUTED = "ActionExecuted"
    CAPABILITY_CREATED = "CapabilityCreated"
    CAPABILITY_UPDATED = "CapabilityUpdated"

    # Learning events
    EXPERIENCE_STORED = "ExperienceStored"

    # Error events
    ERROR_OCCURRED = "errorOccurred"
    HANDLER_FAILED = "HandlerFailed"

    # Loop events
    LOOP_STARTED = "LoopStarted"
    LOOP_COMPLETED = "LoopCompleted"
    LOOP_PAUSED = "LoopPaused"
    LOOP_RESUMED = "LoopResumed"
    LOOP_PHASE_STARTED = "LoopPhaseStarted"
    LOOP_PHASE_COMPLETED = "LoopPhaseCompleted"

    # Health events
    HEALTH_WARNING = "HealthWarning"

    # Task events
    TASK_CREATED = "TaskCreated"
    TASK_ASSIGNED = "TaskAssigned"
    TASK_STARTED = "TaskStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"

    # User message events
    USER_MESSAGE = "UserMessage"
    AI_RESPONSE = "AIResponse"
    LLM_CALL_COMPLETED = "LLMCallCompleted"


# Business event type constants (used by L1 layer storage)
class BusinessEventTypes:
    """
    Business event type constants

    These are filtered and transformed business events
    used for L1 layer storage, focusing on user behavior analysis.
    """

    # User input event (from USER_MESSAGE)
    USER_INPUT = "USER_INPUT"

    # AI response event (from ACTION_EXECUTED, when action_type=ChatResponseAction)
    AI_RESPONSE = "AI_RESPONSE"

    # Tool invocation event (from ACTION_EXECUTED, when action_type is a tool call)
    TOOL_INVOKED = "TOOL_INVOKED"

    # System error event (only records critical errors, level >= ERROR)
    SYSTEM_ERROR = "SYSTEM_ERROR"
