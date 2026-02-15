"""
Self-processing Module

processPerception input，supportcapability积累、failurelearning、人机协作等function
"""
from .module import SelfprocessingModule
from .base import (
    processingResult,
    processingContext,
    TaskComplexity,
    Complexitylevel,
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
    "Complexitylevel",
    "Capability",
    "FailureCase",
    "Failurepattern",
    "LearningStage",
    "ComplexityEvaluator",
]
