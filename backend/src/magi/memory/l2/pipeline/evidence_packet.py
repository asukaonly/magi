"""Deterministic Phase 2 evidence packet assembly."""

from __future__ import annotations

from typing import Any

from ..models import L2EventWindow

MAX_HISTORY_CONTEXTS = 3
MAX_HISTORY_SUPPORT = 12
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
        "history_support": _history_support(candidate_refs, event_window),
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
        claim_id = _text(claim.get("claim_id"))
        if predicate and object_ref:
            refs.append(
                {
                    "kind": "claim_object",
                    "id": claim_id or object_ref,
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


def _history_support(
    candidate_refs: list[dict[str, str]],
    event_window: L2EventWindow,
) -> list[dict[str, Any]]:
    contexts = list(event_window.history_contexts or [])
    if not candidate_refs or not contexts:
        return []

    support_items: list[dict[str, Any]] = []
    seen_refs: set[tuple[str, str]] = set()
    for ref in candidate_refs:
        ref_id = _text(ref.get("id"))
        label = _text(ref.get("label"))
        ref_type = _text(ref.get("type"))
        if not ref_id and not label:
            continue
        ref_key = ((label or ref_id).casefold(), ref_type.casefold())
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)

        matched_event_ids: set[str] = set()
        latest_timestamp = 0.0
        for ctx in contexts:
            if not _history_context_matches_ref(ctx, ref_id=ref_id, label=label):
                continue
            event_id = _text(getattr(ctx, "event_id", ""))
            if event_id and event_id in matched_event_ids:
                continue
            if event_id:
                matched_event_ids.add(event_id)
            timestamp = float(getattr(ctx, "timestamp", 0.0) or 0.0)
            latest_timestamp = max(latest_timestamp, timestamp)

        if matched_event_ids:
            support_items.append(
                {
                    "id": ref_id or label,
                    "label": label or ref_id,
                    "type": ref_type,
                    "history_event_count": len(matched_event_ids),
                    "latest_timestamp": latest_timestamp,
                }
            )

    return sorted(
        support_items,
        key=lambda item: (
            int(item.get("history_event_count", 0) or 0),
            float(item.get("latest_timestamp", 0.0) or 0.0),
            str(item.get("label") or "").casefold(),
        ),
        reverse=True,
    )[:MAX_HISTORY_SUPPORT]


def _history_context_matches_ref(ctx: Any, *, ref_id: str, label: str) -> bool:
    candidates = [ref_id, label]
    matched_entity_id = _text(getattr(ctx, "matched_entity_id", ""))
    canonical_name = _text(getattr(ctx, "canonical_name", ""))
    matched_text = _text(getattr(ctx, "matched_text", ""))
    content = _text(getattr(ctx, "content", ""))
    direct_values = {
        matched_entity_id.casefold(),
        canonical_name.casefold(),
        matched_text.casefold(),
    }
    content_fold = content.casefold()
    for value in candidates:
        folded = value.casefold()
        if not folded:
            continue
        if folded in direct_values:
            return True
        if folded in content_fold:
            return True
    return False


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
