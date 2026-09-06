"""
event system - event data structure definition
"""
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from time import time
import uuid

from .tracing import TraceContext


REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY = "require_subscriber_delivery"
PUBLISHED_MEMORY_EPOCH_METADATA_KEY = "_magi_published_memory_epoch"


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
    event_id: Optional[str] = field(default=None)
    causation_id: Optional[str] = field(default=None)
    trace_context: Optional["TraceContext"] = field(default=None)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Post-initialization processing"""
        if self.event_id is None:
            try:
                from ulid import ULID
                self.event_id = str(ULID())
            except Exception:
                self.event_id = uuid.uuid4().hex
        if self.correlation_id is None:
            self.correlation_id = self.event_id
        if self.trace_context is None:
            try:
                from .tracing import current_trace_context
                self.trace_context = current_trace_context()
            except Exception:
                self.trace_context = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        tc = self.trace_context
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "level": self.level.value,
            "correlation_id": self.correlation_id,
            "event_id": self.event_id,
            "causation_id": self.causation_id,
            "trace_context": (
                {
                    "trace_id": tc.trace_id,
                    "span_id": tc.span_id,
                    "parent_span_id": tc.parent_span_id,
                }
                if tc is not None else None
            ),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create event from dictionary"""
        tc_dict = data.get("trace_context")
        tc = (
            TraceContext(
                trace_id=tc_dict["trace_id"],
                span_id=tc_dict["span_id"],
                parent_span_id=tc_dict.get("parent_span_id"),
            )
            if isinstance(tc_dict, dict) and tc_dict
            else None
        )
        return cls(
            type=data["type"],
            data=data["data"],
            timestamp=data.get("timestamp", time()),
            source=data.get("source", "unknown"),
            level=EventLevel(data.get("level", EventLevel.INFO)),
            correlation_id=data.get("correlation_id"),
            event_id=data.get("event_id"),
            causation_id=data.get("causation_id"),
            trace_context=tc,
            metadata=data.get("metadata", {}),
        )


def published_memory_epoch(event: Event) -> int | None:
    """Return the process-local memory epoch attached when an event was published."""
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    value = metadata.get(PUBLISHED_MEMORY_EPOCH_METADATA_KEY)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


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

    # Context compaction events
    CONTEXT_COMPACTING = "ContextCompacting"
    CONTEXT_COMPACTED = "ContextCompacted"

    # Domain events introduced in 2026-05 refactor
    TOOL_INVOCATION_COMPLETED = "ToolInvocationCompleted"
    USER_MESSAGE_RECEIVED = "UserMessageReceived"
    ASSISTANT_RESPONSE_PRODUCED = "AssistantResponseProduced"
    SOURCE_EVENT_EMITTED = "SourceEventEmitted"
    SPAN_COMPLETED = "SpanCompleted"
    SKILL_INVOCATION_COMPLETED = "SkillInvocationCompleted"

    # Control-plane state-change events (Control-Plane Extraction Phase 1).
    # Emitted by user-facing control tools; consumed by a chat-side subscriber
    # which owns transcript projection. This inverts the former direct
    # control -> chat/transport dependency into a downward control -> events
    # publication that the chat layer subscribes to.
    CONTROL_PLAN_STATE_CHANGED = "control.plan_state_changed"
    CONTROL_ASK_REQUESTED = "control.ask_requested"
    CONTROL_ASK_ANSWERED = "control.ask_answered"
