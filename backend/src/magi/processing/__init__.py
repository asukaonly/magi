"""
自处理模块

处理感知输入，支持能力积累、失败学习、人机协作等功能
"""
from .module import SelfProcessingModule
from .base import (
    ProcessingResult,
    ProcessingContext,
    TaskComplexity,
    ComplexityLevel,
    Capability,
    FailureCase,
    FailurePattern,
    LearningStage,
)
from .complexity import ComplexityEvaluator

__all__ = [
    "SelfProcessingModule",
    "ProcessingResult",
    "ProcessingContext",
    "TaskComplexity",
    "ComplexityLevel",
    "Capability",
    "FailureCase",
    "FailurePattern",
    "LearningStage",
    "ComplexityEvaluator",
]
