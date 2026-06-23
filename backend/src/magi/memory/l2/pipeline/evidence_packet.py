"""Deterministic Phase 2 evidence packet assembly."""

from __future__ import annotations

from typing import Any

from ..models import L2EventWindow

MAX_HISTORY_CONTEXTS = 3
MAX_RELATED_EDGES = 12
MAX_EXISTING_ASSERTIONS = 8


def build_phase2_evidence_packet(
    *,
    phase1_result: Any,
    existing_graph_edges: list[dict[str, Any]] | None,
    existing_assertions: list[dict[str, Any]] | None,
    event_window: L2EventWindow,
) -> dict[str, Any]:
    """Build a no-LLM evidence packet for Phase 2 integration."""
    phase1_payload = phase1_result.to_dict() if hasattr(phase1_result, "to_dict") else dict(phase1_result or {})
    candidate_refs = _candidate_refs(phase1_payload)
    return {
        "retrieval_method": "deterministic",
        "llm_used": False,
        "candidate_refs": candidate_refs[:12],
        "history_contexts": _compact_history_contexts(event_window),
        "related_edges": _compact_edges(existing_graph_edges or []),
        "existing_assertions": _compact_assertions(existing_assertions or []),
        "promotion_guardrails": [
            "Single passive behavior is evidence, not a stable user profile assertion.",
            "Prefer graph corroboration when evidence is passive, recent, or single-source.",
            "User-authored assertions must outrank external activity in conflicts.",
        ],
    }


def _candidate_refs(phase1_payload: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for entity in phase1_payload.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        resolved_id = _text(entity.get("resolved_id"))
        surface = _text(entity.get("surface"))
        entity_type = _text(entity.get("entity_type"))
        if resolved_id or surface:
            refs.append(
                {
                    "kind": "entity",
                    "id": resolved_id or surface,
                    "label": surface or resolved_id,
                    "type": entity_type,
                }
            )
    for claim in phase1_payload.get("fact_claims") or []:
        if not isinstance(claim, dict):
            continue
        predicate = _text(claim.get("predicate"))
        object_ref = _text(claim.get("object_ref"))
        object_type = _text(claim.get("object_type"))
        if predicate and object_ref:
            refs.append(
                {
                    "kind": "claim_object",
                    "id": object_ref,
                    "label": object_ref,
                    "type": object_type,
                    "predicate": predicate,
                }
            )
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for ref in refs:
        key = (ref.get("kind", ""), ref.get("id", "").casefold(), ref.get("type", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def _compact_history_contexts(event_window: L2EventWindow) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for ctx in list(event_window.history_contexts or [])[:MAX_HISTORY_CONTEXTS]:
        contexts.append(
            {
                "event_id": ctx.event_id,
                "timestamp": ctx.timestamp,
                "session_id": ctx.session_id,
                "matched_entity_id": ctx.matched_entity_id,
                "matched_text": ctx.matched_text,
                "canonical_name": ctx.canonical_name,
                "match_source": ctx.match_source,
                "content": _clip(ctx.content, 220),
            }
        )
    return contexts


def _compact_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for edge in sorted(
        edges,
        key=lambda item: (
            int(item.get("observation_count", 0) or 0),
            float(item.get("last_observed_at", 0.0) or 0.0),
        ),
        reverse=True,
    )[:MAX_RELATED_EDGES]:
        evidence_ids = list(edge.get("evidence_event_ids") or [])
        compact.append(
            {
                "triple_id": _text(edge.get("triple_id")),
                "subject_id": _text(edge.get("subject_id")),
                "predicate": _text(edge.get("predicate")),
                "object_id": _text(edge.get("object_id")),
                "object_type": _text(edge.get("object_type")),
                "source_type": _text(edge.get("source_type")),
                "evidence_class": _text(edge.get("evidence_class")),
                "observation_count": int(edge.get("observation_count", 0) or 0),
                "evidence_event_count": len(evidence_ids),
                "first_observed_at": float(edge.get("first_observed_at", 0.0) or 0.0),
                "last_observed_at": float(edge.get("last_observed_at", 0.0) or 0.0),
                "confidence": float(edge.get("confidence", 0.0) or 0.0),
            }
        )
    return compact


def _compact_assertions(assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for assertion in sorted(
        assertions,
        key=lambda item: (
            str(item.get("validation_state") or item.get("status") or ""),
            float(item.get("confidence_score", 0.0) or 0.0),
        ),
        reverse=True,
    )[:MAX_EXISTING_ASSERTIONS]:
        compact.append(
            {
                "assertion_id": _text(assertion.get("assertion_id")),
                "trait_family": _text(assertion.get("trait_family")),
                "trait_name": _text(assertion.get("trait_name")),
                "trait_value": _clip(assertion.get("trait_value"), 80),
                "validation_state": _text(
                    assertion.get("validation_state") or assertion.get("status")
                ),
                "source_domain": _text(assertion.get("source_domain")),
                "confidence_score": float(assertion.get("confidence_score", 0.0) or 0.0),
            }
        )
    return compact


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: Any, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


__all__ = ["build_phase2_evidence_packet"]
