"""Validation mixin compatibility hub for L2Pipeline."""

from __future__ import annotations

from .pipeline_assertions import L2AssertionValidationMixin, classify_memory_subdomain
from .pipeline_graph_validation import L2GraphValidationMixin
from .pipeline_structured_hints import L2StructuredHintMixin

__all__ = ["L2ValidationMixin", "classify_memory_subdomain"]


class L2ValidationMixin(
    L2GraphValidationMixin,
    L2StructuredHintMixin,
    L2AssertionValidationMixin,
):
    """Compose graph, structured hint, and assertion validation helpers."""
