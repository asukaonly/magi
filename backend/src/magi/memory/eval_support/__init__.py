"""Public exports for benchmark-agnostic memory evaluation support."""

from .contracts import (
    EvalMemoryHit,
    EvalMemoryQuery,
    EvalMemoryQueryResult,
    EvalMemoryWriteRecord,
)
from .namespace import EvalNamespaceManager, build_eval_namespace, sanitize_eval_namespace_component
from .reader import EvalMemoryReader
from .service import EvalMemoryService
from .writer import EvalMemoryWriter

__all__ = [
    "EvalNamespaceManager",
    "EvalMemoryHit",
    "EvalMemoryReader",
    "EvalMemoryService",
    "EvalMemoryQuery",
    "EvalMemoryQueryResult",
    "EvalMemoryWriteRecord",
    "EvalMemoryWriter",
    "build_eval_namespace",
    "sanitize_eval_namespace_component",
]
