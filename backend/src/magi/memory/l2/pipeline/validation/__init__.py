"""Validation mixin compatibility hub for L2Pipeline."""

from __future__ import annotations

from .assertions import L2AssertionValidationMixin, classify_memory_subdomain
from .graph import L2GraphValidationMixin
from .structured_hints import L2StructuredHintMixin

__all__ = ["L2ValidationMixin", "classify_memory_subdomain"]


class L2ValidationMixin(
    L2GraphValidationMixin,
    L2StructuredHintMixin,
    L2AssertionValidationMixin,
):
    """Compose graph, structured hint, and assertion validation helpers."""
