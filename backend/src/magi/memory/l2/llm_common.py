"""Shared helpers for L2 LLM prompt services."""

from __future__ import annotations

from typing import Any

from .models import L2EntityResolution


class L2LLMCommonMixin:
    """Small shared helpers for L2 LLM result normalization."""

    def _unresolved_resolution(self, *, confidence: float = 0.0) -> L2EntityResolution:
        return L2EntityResolution(
            confidence=float(confidence),
            reason_tags=["insufficient_evidence"],
        )

    def _non_empty_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = ["L2LLMCommonMixin"]
