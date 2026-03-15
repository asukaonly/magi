"""
Self-processing Module - Core Data Structures
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict
import time


class ComplexityLevel(Enum):
    """Complexity level"""
    LOW = "low"                  # Handle autonomously
    MEDIUM = "medium"            # Can handle autonomously
    HIGH = "high"                # Needs confirmation
    CRITICAL = "critical"        # Requires human involvement


class LearningStage(Enum):
    """Learning stage"""
    INITIAL = "initial"          # Initial stage (first 100 interactions)
    GROWTH = "growth"            # Growth stage (100-1000 interactions)
    MATURE = "mature"            # Mature stage (over 1000 interactions)


@dataclass
class TaskComplexity:
    """Task complexity"""
    level: ComplexityLevel
    score: float                        # Complexity score (0-100)
    tool_count: int = 0                 # Number of tools
    step_count: int = 0                 # Number of steps
    parameter_uncertainty: float = 0.0  # Parameter uncertainty (0-1)
    dependency_count: int = 0           # Number of dependencies


@dataclass
class Capability:
    """Extracted capability"""
    name: str
    description: str
    trigger_pattern: str               # Trigger pattern
    required_tools: List[str]          # Required tools
    execution_steps: List[Dict]        # Execution steps
    success_rate: float = 0.0          # Success rate
    usage_count: int = 0               # Usage count
    verified: bool = False             # Whether verified
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)


@dataclass
class FailureCase:
    """Failure case"""
    task_description: str
    failure_reason: str
    error_stack: str
    execution_steps: List[Dict]
    timestamp: float = field(default_factory=time.time)


@dataclass
class Failurepattern:
    """Failure pattern"""
    pattern_id: str
    description: str
    avoidance_strategy: str
    case_count: int
    created_at: float = field(default_factory=time.time)


@dataclass
class processingContext:
    """Processing context"""
    user_status: Dict[str, Any]        # User status
    system_status: Dict[str, Any]      # System status
    recent_tasks: List[Dict]           # Recent tasks
    current_time: float = field(default_factory=time.time)


@dataclass
class processingResult:
    """Processing result"""
    action: Dict[str, Any]             # Action
    needs_human_help: bool = False     # Whether human help is needed
    complexity: TaskComplexity = None
    human_help_context: Dict = None    # Human help context
    metadata: Dict = field(default_factory=dict)
