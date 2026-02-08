"""
自处理模块 - 核心数据结构
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict
import time


class ComplexityLevel(Enum):
    """复杂度级别"""
    LOW = "low"                  # 自主处理
    MEDIUM = "medium"            # 可自主
    HIGH = "high"                # 需确认
    CRITICAL = "critical"        # 必须人类


class LearningStage(Enum):
    """学习阶段"""
    INITIAL = "initial"          # 初始阶段（前100次）
    GROWTH = "growth"            # 成长阶段（100-1000次）
    MATURE = "mature"            # 成熟阶段（1000次以上）


@dataclass
class TaskComplexity:
    """任务复杂度"""
    level: ComplexityLevel
    score: float                        # 复杂度分数 (0-100)
    tool_count: int = 0                 # 工具数量
    step_count: int = 0                 # 步骤数量
    parameter_uncertainty: float = 0.0  # 参数不确定性 (0-1)
    dependency_count: int = 0           # 依赖关系数


@dataclass
class Capability:
    """提取的能力"""
    name: str
    description: str
    trigger_pattern: str               # 触发模式
    required_tools: List[str]          # 所需工具
    execution_steps: List[Dict]        # 执行步骤
    success_rate: float = 0.0          # 成功率
    usage_count: int = 0               # 使用次数
    verified: bool = False             # 是否已验证
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


@dataclass
class FailureCase:
    """失败案例"""
    task_description: str
    failure_reason: str
    error_stack: str
    execution_steps: List[Dict]
    timestamp: float = field(default_factory=time.time)


@dataclass
class FailurePattern:
    """失败模式"""
    pattern_id: str
    description: str
    avoidance_strategy: str
    case_count: int
    created_at: float = field(default_factory=time.time)


@dataclass
class ProcessingContext:
    """处理上下文"""
    user_status: Dict[str, Any]        # 用户状态
    system_status: Dict[str, Any]      # 系统状态
    recent_tasks: List[Dict]           # 最近任务
    current_time: float = field(default_factory=time.time)


@dataclass
class ProcessingResult:
    """处理结果"""
    action: Dict[str, Any]             # 动作
    needs_human_help: bool = False     # 是否需要人类帮助
    complexity: TaskComplexity = None
    human_help_context: Dict = None    # 人类帮助上下文
    metadata: Dict = field(default_factory=dict)
