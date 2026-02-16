"""
Self-processing Module - coredatastructure
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict
import time


class Complexitylevel(Enum):
    """complex度level"""
    LOW = "low"                  # 自主process
    MEDIUM = "medium"            # 可自主
    HIGH = "high"                # 需确认
    CRITICAL = "critical"        # 必须人Class


class LearningStage(Enum):
    """learning阶段"""
    INITIAL = "initial"          # 初始阶段（前100次）
    GrowTH = "growth"            # growth阶段（100-1000次）
    MATURE = "mature"            # 成熟阶段（1000次以上）


@dataclass
class TaskComplexity:
    """任务complex度"""
    level: Complexitylevel
    score: float                        # complex度score (0-100)
    tool_count: int = 0                 # toolquantity
    step_count: int = 0                 # stepquantity
    parameter_uncertainty: float = 0.0  # Parameter不确定性 (0-1)
    dependency_count: int = 0           # dependencyrelationship数


@dataclass
class Capability:
    """提取的capability"""
    name: str
    description: str
    trigger_pattern: str               # 触发pattern
    required_tools: List[str]          # 所需tool
    execution_steps: List[Dict]        # Executestep
    success_rate: float = 0.0          # success率
    usage_count: int = 0               # 使用count
    verified: bool = False             # is not已Validate
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


@dataclass
class FailureCase:
    """failurecase"""
    task_description: str
    failure_reason: str
    error_stack: str
    execution_steps: List[Dict]
    timestamp: float = field(default_factory=time.time)


@dataclass
class Failurepattern:
    """failurepattern"""
    pattern_id: str
    description: str
    avoidance_strategy: str
    case_count: int
    created_at: float = field(default_factory=time.time)


@dataclass
class processingContext:
    """processcontext"""
    user_status: Dict[str, Any]        # userState
    system_status: Dict[str, Any]      # 系统State
    recent_tasks: List[Dict]           # 最近任务
    current_time: float = field(default_factory=time.time)


@dataclass
class processingResult:
    """processResult"""
    action: Dict[str, Any]             # action
    needs_human_help: bool = False     # is not需要人Class帮助
    complexity: TaskComplexity = None
    human_help_context: Dict = None    # 人Class帮助context
    metadata: Dict = field(default_factory=dict)
