"""Candidate manifest assembly for cross-layer retrieval selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import RetrievalPayload

ManifestCandidate = Tuple[str, str]
ManifestIndex = Tuple[str, int]

_FIELD_TO_ATTR = {
    "l1_events": "l1_events",
    "l2_entity_cards": "l2_entity_cards",
    "l2_relationships": "l2_relationships",
    "l2_assertions": "l2_assertions",
    "l2_experiences": "l2_experiences",
    "l3_reflections": "l3_reflections",
    "l4_procedures": "l4_procedures",
}


@dataclass(frozen=True)
class ManifestCandidates:
    """Flat selector candidates plus their source payload positions."""

    candidates: List[ManifestCandidate]
    index_map: List[ManifestIndex]


def build_manifest_candidates(
    payload: RetrievalPayload,
    *,
    max_chars: int,
) -> ManifestCandidates:
    """Build flat, numbered selector candidates across memory layers."""
    safe_max_chars = max(50, max_chars)
    candidates: List[ManifestCandidate] = []
    index_map: List[ManifestIndex] = []

    _append_l1_event_candidates(payload, candidates, index_map, safe_max_chars)
    _append_l2_entity_card_candidates(payload, candidates, index_map, safe_max_chars)
    _append_l2_relationship_candidates(payload, candidates, index_map, safe_max_chars)
    _append_l2_assertion_candidates(payload, candidates, index_map, safe_max_chars)
    _append_l2_experience_candidates(payload, candidates, index_map, safe_max_chars)
    _append_l3_reflection_candidates(payload, candidates, index_map, safe_max_chars)
    _append_l4_procedure_candidates(payload, candidates, index_map, safe_max_chars)
    return ManifestCandidates(candidates=candidates, index_map=index_map)


def apply_manifest_selection(
    payload: RetrievalPayload,
    selected_indices: List[int],
    index_map: List[ManifestIndex],
) -> RetrievalPayload:
    """Rebuild payload keeping only selected candidates in LLM-ranked order."""
    selected_by_field: Dict[str, List[int]] = {}
    for global_idx in selected_indices:
        if global_idx >= len(index_map):
            continue
        field_name, original_idx = index_map[global_idx]
        selected_by_field.setdefault(field_name, []).append(original_idx)

    for field_name, attr_name in _FIELD_TO_ATTR.items():
        original = getattr(payload, attr_name)
        if field_name in selected_by_field:
            ordered_indices = selected_by_field[field_name]
            setattr(
                payload,
                attr_name,
                [original[i] for i in ordered_indices if i < len(original)],
            )
        else:
            setattr(payload, attr_name, [])

    return payload


def truncate_manifest_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars with ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _append_candidate(
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    *,
    layer: str,
    text: str,
    field_name: str,
    original_index: int,
) -> None:
    candidates.append((layer, text))
    index_map.append((field_name, original_index))


def _append_l1_event_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, ev in enumerate(payload.l1_events):
        text = truncate_manifest_text(str(ev.get("content") or ""), max_chars)
        ts = ev.get("timestamp") or ""
        snippet = f"[{ts}] {text}" if ts else text
        _append_candidate(
            candidates,
            index_map,
            layer="L1",
            text=snippet,
            field_name="l1_events",
            original_index=i,
        )


def _append_l2_entity_card_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, card in enumerate(payload.l2_entity_cards):
        name = card.get("name") or card.get("entity_id") or ""
        entity_type = card.get("entity_type") or ""
        attrs = card.get("attributes") or {}
        text = truncate_manifest_text(
            f"{name} ({entity_type}): {json.dumps(attrs, ensure_ascii=False)}",
            max_chars,
        )
        _append_candidate(
            candidates,
            index_map,
            layer="L2",
            text=text,
            field_name="l2_entity_cards",
            original_index=i,
        )


def _append_l2_relationship_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, rel in enumerate(payload.l2_relationships):
        subj = rel.get("subject_name") or rel.get("subject_id") or ""
        pred = rel.get("predicate") or ""
        obj = rel.get("object_name") or rel.get("object_id") or ""
        text = truncate_manifest_text(f"{subj} --{pred}--> {obj}", max_chars)
        _append_candidate(
            candidates,
            index_map,
            layer="L2",
            text=text,
            field_name="l2_relationships",
            original_index=i,
        )


def _append_l2_assertion_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, assertion in enumerate(payload.l2_assertions):
        entity = assertion.get("entity_name") or assertion.get("entity_id") or ""
        trait = assertion.get("trait_family") or ""
        value = assertion.get("value") or assertion.get("content") or ""
        text = truncate_manifest_text(f"{entity} [{trait}]: {value}", max_chars)
        _append_candidate(
            candidates,
            index_map,
            layer="L2",
            text=text,
            field_name="l2_assertions",
            original_index=i,
        )


def _append_l2_experience_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, experience in enumerate(payload.l2_experiences):
        title = experience.get("user_label") or experience.get("title") or ""
        interpretation = experience.get("magi_interpretation") or experience.get("user_note") or ""
        text = truncate_manifest_text(f"{title}: {interpretation}", max_chars)
        _append_candidate(
            candidates,
            index_map,
            layer="L2",
            text=text,
            field_name="l2_experiences",
            original_index=i,
        )


def _append_l3_reflection_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, refl in enumerate(payload.l3_reflections):
        text = truncate_manifest_text(
            str(refl.get("content") or refl.get("summary") or ""),
            max_chars,
        )
        period = refl.get("period") or ""
        snippet = f"[{period}] {text}" if period else text
        _append_candidate(
            candidates,
            index_map,
            layer="L3",
            text=snippet,
            field_name="l3_reflections",
            original_index=i,
        )


def _append_l4_procedure_candidates(
    payload: RetrievalPayload,
    candidates: List[ManifestCandidate],
    index_map: List[ManifestIndex],
    max_chars: int,
) -> None:
    for i, proc in enumerate(payload.l4_procedures):
        text = truncate_manifest_text(
            str(proc.get("optimized_prompt") or proc.get("content") or ""),
            max_chars,
        )
        _append_candidate(
            candidates,
            index_map,
            layer="L4",
            text=text,
            field_name="l4_procedures",
            original_index=i,
        )
