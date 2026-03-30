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


def build_l4_embedding_text(
    *,
    skill_name: str,
    skill_category: str,
    optimized_prompt: str | None,
) -> str:
    """Return the canonical L4 text used for embedding."""
    parts = [str(skill_name).strip(), str(skill_category).strip()]
    prompt = str(optimized_prompt or "").strip()
    if prompt:
        parts.append(prompt)
    return "\n".join(part for part in parts if part)


__all__ = ["build_l1_embedding_text", "build_l3_embedding_text", "build_l4_embedding_text"]
