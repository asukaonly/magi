"""Shared text builders for memory embedding inputs."""

from __future__ import annotations

from typing import Any

from .event_contracts import MemoryEvent


def build_l1_embedding_text(event: MemoryEvent) -> str:
    """Return the canonical L1 text used for embedding."""
    return str(event.content or "").strip()


def build_l3_embedding_text(summary: dict[str, Any]) -> str:
    """Return the canonical L3 text used for embedding."""
    return str(summary.get("content") or "").strip()


__all__ = ["build_l1_embedding_text", "build_l3_embedding_text"]
