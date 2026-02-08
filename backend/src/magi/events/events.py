"""
事件系统 - Event数据结构定义
"""
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from time import time
import uuid


class EventLevel(IntEnum):
    """
    事件等级（影响优先级和持久化策略）

    0: DEBUG     - 调试信息
    1: INFO      - 普通信息
    2: WARNING   - 警告
    3: ERROR     - 错误
    4: CRITICAL  - 严重错误
    5: EMERGENCY - 紧急事件（最高优先级）
    """
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4
    EMERGENCY = 5


class PropagationMode:
    """事件传播模式"""
    BROADCAST = "broadcast"  # 广播：所有订阅者都收到
    COMPETING = "competing"  # 竞争：只有一个订阅者收到


@dataclass
class Event:
    """
    事件数据结构

    Attributes:
        type: 事件类型（如 "AgentStarted", "PerceptionReceived"）
        data: 事件数据（可以是任意类型）
        timestamp: 时间戳
        source: 事件源（可以是Agent ID、模块名等）
        level: 事件等级（影响优先级和持久化策略）
        correlation_id: 关联ID（用于追踪事件链）
        metadata: 额外元数据
    """
    type: str
    data: Any
    timestamp: float = field(default_factory=time)
    source: str = "unknown"
    level: EventLevel = EventLevel.INFO
    correlation_id: Optional[str] = field(default=None)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后处理"""
        if self.correlation_id is None:
            # 生成唯一的关联ID
            self.correlation_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
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
        """从字典创建Event"""
        return cls(
            type=data["type"],
            data=data["data"],
            timestamp=data.get("timestamp", time()),
            source=data.get("source", "unknown"),
            level=EventLevel(data.get("level", EventLevel.INFO)),
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {}),
        )


# 核心事件类型定义
class EventTypes:
    """核心事件类型常量"""

    # 生命周期事件
    AGENT_STARTED = "AgentStarted"
    AGENT_STOPPED = "AgentStopped"
    STATE_CHANGED = "StateChanged"

    # 感知事件
    PERCEPTION_RECEIVED = "PerceptionReceived"
    PERCEPTION_PROCESSED = "PerceptionProcessed"

    # 处理事件
    ACTION_EXECUTED = "ActionExecuted"
    CAPABILITY_CREATED = "CapabilityCreated"
    CAPABILITY_UPDATED = "CapabilityUpdated"

    # 学习事件
    EXPERIENCE_STORED = "ExperienceStored"

    # 错误事件
    ERROR_OCCURRED = "ErrorOccurred"
    HANDLER_FAILED = "HandlerFailed"

    # 循环事件
    LOOP_STARTED = "LoopStarted"
    LOOP_COMPLETED = "LoopCompleted"
    LOOP_PHASE_STARTED = "LoopPhaseStarted"
    LOOP_PHASE_COMPLETED = "LoopPhaseCompleted"

    # 任务事件
    TASK_CREATED = "TaskCreated"
    TASK_ASSIGNED = "TaskAssigned"
    TASK_STARTED = "TaskStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
