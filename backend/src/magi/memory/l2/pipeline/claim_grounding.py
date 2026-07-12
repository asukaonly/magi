"""Deterministic evidence grounding for Phase 1 fact claims."""

from __future__ import annotations

import re
import unicodedata

from ..models import L2BatchEvent, L2EventWindow, L2Phase1FactClaim, L2Phase1Result


def ground_phase1_fact_claims(
    phase1_result: L2Phase1Result,
    event_window: L2EventWindow,
) -> dict[str, int]:
    """Keep only claims grounded in exact current-window evidence."""
    eligible_events = _eligible_evidence_events(event_window)
    event_ids = {event.event_id for event, _content in eligible_events}
    grounded_claims: list[L2Phase1FactClaim] = []
    rejected_count = 0
    rebound_count = 0

    for claim_index, claim in enumerate(phase1_result.fact_claims, start=1):
        original_event_ids = _unique_event_ids(claim.supporting_event_ids)
        valid_original_ids = [event_id for event_id in original_event_ids if event_id in event_ids]
        grounded_event_ids = _grounded_event_ids(
            claim=claim,
            eligible_events=eligible_events,
            valid_original_ids=valid_original_ids,
        )
        if not grounded_event_ids:
            rejected_count += 1
            continue
        if grounded_event_ids != valid_original_ids and original_event_ids:
            rebound_count += 1
        claim.supporting_event_ids = grounded_event_ids
        claim.claim_id = f"claim:{claim_index}"
        grounded_claims.append(claim)

    phase1_result.fact_claims = grounded_claims
    return {
        "kept": len(grounded_claims),
        "rejected": rejected_count,
        "rebound": rebound_count,
    }


def _grounded_event_ids(
    *,
    claim: L2Phase1FactClaim,
    eligible_events: list[tuple[L2BatchEvent, str]],
    valid_original_ids: list[str],
) -> list[str]:
    evidence_text = _normalize_evidence_text(claim.evidence_text)
    if evidence_text:
        return [
            event.event_id
            for event, content in eligible_events
            if evidence_text in _normalize_evidence_text(content)
        ]
    if len(eligible_events) != 1:
        return []
    only_event_id = eligible_events[0][0].event_id
    if valid_original_ids and valid_original_ids != [only_event_id]:
        return []
    return [only_event_id]


def _eligible_evidence_events(
    event_window: L2EventWindow,
) -> list[tuple[L2BatchEvent, str]]:
    events = list(event_window.events)
    window_texts = list(event_window.texts)
    texts_are_aligned = len(window_texts) == len(events)
    return [
        (
            event,
            window_texts[index] if texts_are_aligned else event.content,
        )
        for index, event in enumerate(events)
        if _is_evidence_event(event)
    ]


def _is_evidence_event(event: L2BatchEvent) -> bool:
    return str(event.author_type or "").strip().casefold() != "assistant"


def _normalize_evidence_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _unique_event_ids(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        event_id = str(value or "").strip()
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        unique.append(event_id)
    return unique


__all__ = ["ground_phase1_fact_claims"]
