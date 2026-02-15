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
    Taskdatabase,
    Task,
    TaskStatus,
    Taskpriority,
)
from .monitoring import SystemMonitor, AgentMetrics, SystemMetrics
from .timeout import (
    TimeoutCalculator,
    Tasktype,
    Taskpriority as TimeoutTaskpriority,
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
    "Taskdatabase",
    "Task",
    "TaskStatus",
    "Taskpriority",

    # monitor
    "SystemMonitor",
    "AgentMetrics",
    "SystemMetrics",

    # timeoutcalculate
    "TimeoutCalculator",
    "Tasktype",
    "TimeoutTaskpriority",

    # 生命period管理
    "GracefulShutdownManager",
    "AgentLifecycleManager",
    "ShutdownState",
]
