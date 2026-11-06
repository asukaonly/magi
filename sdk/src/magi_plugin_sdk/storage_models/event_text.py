"""Portable persistence values and deterministic row normalization."""

from __future__ import annotations
from typing import Any
from .events import MemoryEvent


def build_l1_embedding_text(event: MemoryEvent) -> str:
    """Return the canonical L1 text used for embedding."""
    content = str(event.content or "").strip()
    projection = _get_l1_projection(event)
    embedding_head = str(projection.get("embedding_head") or "").strip()
    retrieval_terms_text = build_l1_retrieval_terms_text(event)

    parts: list[str] = []
    if embedding_head:
        parts.append(embedding_head)
    if content and content != embedding_head:
        parts.append(content)
    if retrieval_terms_text:
        lowered_parts = {part.lower() for part in parts}
        if retrieval_terms_text.lower() not in lowered_parts:
            parts.append(retrieval_terms_text)
    return "\n".join(parts)


def build_l1_retrieval_terms_text(event: MemoryEvent) -> str:
    """Return auxiliary retrieval terms stored in the L1 projection metadata."""
    projection = _get_l1_projection(event)
    values = projection.get("retrieval_terms") or []
    terms: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, list) else []:
        term = str(value or "").strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return " ".join(terms)


def _get_l1_projection(event: MemoryEvent) -> dict[str, Any]:
    projection = {}
    if isinstance(event.metadata_json, dict):
        projection = dict(event.metadata_json.get("projection") or {})
    return projection
