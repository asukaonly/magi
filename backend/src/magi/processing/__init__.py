"""
Self-processing Module

Process perception input, supporting capability accumulation, failure learning,
human-agent collaboration, and other functions.
"""
from .module import SelfprocessingModule
from .base import (
    processingResult,
    processingContext,
    TaskComplexity,
    ComplexityLevel,
    Capability,
    FailureCase,
    Failurepattern,
    LearningStage,
)
from .complexity import ComplexityEvaluator

__all__ = [
    "SelfprocessingModule",
    "processingResult",
    "processingContext",
    "TaskComplexity",
    "ComplexityLevel",
    "Capability",
    "FailureCase",
    "Failurepattern",
    "LearningStage",
    "ComplexityEvaluator",
]
