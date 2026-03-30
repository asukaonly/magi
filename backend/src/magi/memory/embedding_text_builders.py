"""Shared text builders for memory embedding inputs."""

from __future__ import annotations

from .event_contracts import MemoryEvent


def build_l1_embedding_text(event: MemoryEvent) -> str:
    """Return the canonical L1 text used for embedding."""
    return str(event.content or "").strip()


__all__ = ["build_l1_embedding_text"]
