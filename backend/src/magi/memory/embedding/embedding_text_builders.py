"""Shared text builders for memory embedding inputs."""

from __future__ import annotations

from typing import Any

from ..event_contracts import MemoryEvent


def build_l1_embedding_text(event: MemoryEvent) -> str:
    """Return the canonical L1 text used for embedding."""
    return str(event.content or "").strip()


def build_l3_embedding_text(summary: dict[str, Any]) -> str:
    """Return the canonical L3 text used for embedding."""
    return str(summary.get("content") or "").strip()


def build_l2_entity_embedding_text(
    *,
    canonical_name: str,
    entity_type: str,
    aliases: list[str] | None = None,
) -> str:
    """Return the canonical L2 text used for embedding."""
    parts = [str(entity_type).strip(), str(canonical_name).strip()]
    alias_texts = [str(alias).strip() for alias in aliases or [] if str(alias).strip()]
    parts.extend(alias_texts)
    return "\n".join(part for part in parts if part)


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


def build_l2_edge_embedding_text(
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    evidence_text: str | None = None,
    natural_summary: str | None = None,
) -> str:
    """Return the canonical text for a knowledge-graph edge embedding.

    Combines the triple's structural identity with its evidence to enable
    semantic similarity search across edges.
    """
    parts = [f"{subject_id} {predicate} {object_id}"]
    summary = str(natural_summary or "").strip()
    if summary:
        parts.append(summary)
    evidence = str(evidence_text or "").strip()
    if evidence:
        parts.append(evidence)
    return "\n".join(parts)


__all__ = [
    "build_l1_embedding_text",
    "build_l2_entity_embedding_text",
    "build_l2_edge_embedding_text",
    "build_l3_embedding_text",
    "build_l4_embedding_text",
]
