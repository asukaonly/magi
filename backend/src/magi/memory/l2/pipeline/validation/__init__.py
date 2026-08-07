"""Validation mixins for graph and structured source hints."""

from __future__ import annotations

from .graph import L2GraphValidationMixin
from .structured_hints import L2StructuredHintMixin

__all__ = ["L2ValidationMixin"]


class L2ValidationMixin(
    L2GraphValidationMixin,
    L2StructuredHintMixin,
):
    """Compose graph and structured source-hint validation helpers."""
