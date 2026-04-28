"""Shared text builders for memory embedding inputs."""

from __future__ import annotations

from typing import Any

from ..event_contracts import MemoryEvent


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
    """Return the canonical L4 text used for embedding.

    When *optimized_prompt* contains a JSON strategy (from LLM extraction),
    the embedding text includes structured strategy fields for richer
    semantic retrieval.
    """
    import json

    parts = [str(skill_name).strip(), str(skill_category).strip()]
    prompt = str(optimized_prompt or "").strip()
    if prompt:
        # Try to expand strategy JSON into more descriptive text.
        try:
            data = json.loads(prompt)
            if isinstance(data, dict) and any(
                k in data for k in ("recommended_approach", "best_use_cases", "avoid_patterns")
            ):
                approach = str(data.get("recommended_approach") or "").strip()
                if approach:
                    parts.append(approach)
                for case in data.get("best_use_cases") or []:
                    case_text = str(case).strip()
                    if case_text:
                        parts.append(case_text)
                for pattern in data.get("avoid_patterns") or []:
                    pattern_text = str(pattern).strip()
                    if pattern_text:
                        parts.append(f"avoid: {pattern_text}")
            else:
                # Non-strategy JSON or plain text — include as-is.
                parts.append(prompt)
        except (json.JSONDecodeError, TypeError):
            parts.append(prompt)
    return "\n".join(part for part in parts if part)


def build_l2_edge_embedding_text(
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    evidence_text: str | None = None,
    natural_summary: str | None = None,
    subject_name: str | None = None,
    object_name: str | None = None,
) -> str:
    """Return the canonical text for a knowledge-graph edge embedding.

    When *subject_name* or *object_name* are available the embedding text
    uses human-readable names instead of opaque entity IDs, which yields
    higher-quality semantic vectors.
    """
    subj = subject_name or subject_id
    obj = object_name or object_id
    parts = [f"{subj} {predicate} {obj}"]
    summary = str(natural_summary or "").strip()
    if summary:
        parts.append(summary)
    evidence = str(evidence_text or "").strip()
    if evidence:
        parts.append(evidence)
    return "\n".join(parts)


__all__ = [
    "build_l1_embedding_text",
    "build_l1_retrieval_terms_text",
    "build_l2_entity_embedding_text",
    "build_l2_edge_embedding_text",
    "build_l3_embedding_text",
    "build_l4_embedding_text",
]
