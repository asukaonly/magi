"""
Agentcoremodule

containsAgentBase class、MasterAgent、TaskAgent、WorkerAgent等corecomponent
"""
from .agent import Agent, AgentConfig, AgentState
from .master_agent import MasterAgent
from .task_agent import TaskAgent
from .worker_agent import WorkerAgent, WorkerAgentConfig
from .loop import LoopEngine, Loopstrategy
from .task_database import (
    TaskDatabase,
    Task,
    TaskStatus,
    TaskPriority,
)
from .monitoring import SystemMonitor, AgentMetrics, SystemMetrics
from .timeout import (
    TimeoutCalculator,
    TaskType,
    TaskPriority as TimeoutTaskPriority,
)
from .lifecycle import (
    GracefulShutdownManager,
    AgentLifecycleManager,
    ShutdownState,
)

__all__ = [
    # Agentbase
    "Agent",
    "AgentConfig",
    "AgentState",

    # 三层Agent
    "MasterAgent",
    "TaskAgent",
    "WorkerAgent",
    "WorkerAgentConfig",

    # Loop Engine
    "LoopEngine",
    "Loopstrategy",

    # 任务database
    "TaskDatabase",
    "Task",
    "TaskStatus",
    "TaskPriority",

    # monitor
    "SystemMonitor",
    "AgentMetrics",
    "SystemMetrics",

    # timeoutcalculate
    "TimeoutCalculator",
    "TaskType",
    "TimeoutTaskPriority",

    # 生命period管理
    "GracefulShutdownManager",
    "AgentLifecycleManager",
    "ShutdownState",
]
