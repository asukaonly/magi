"""Deterministic evidence grounding for Phase 1 fact claims."""

from __future__ import annotations

import re
import unicodedata

from ..models import L2BatchEvent, L2EventWindow, L2Phase1FactClaim, L2Phase1Result
from ..phase1_models import L2TemporalCue

_TEMPORAL_CUE_PATTERNS: dict[L2TemporalCue, tuple[re.Pattern[str], ...]] = {
    L2TemporalCue.ONE_OFF: (
        re.compile(r"昨晚|昨天|刚刚|刚才|这一次|这次|只.{0,4}一次|首次|第一次|最后一次"),
        re.compile(r"\b(?:last night|yesterday|just now|this time|only once|once|first time)\b"),
        re.compile(r"\b(?:today|now)\b"),
    ),
    L2TemporalCue.RECENT: (
        re.compile(r"最近|近期|目前|现在|这几天|这些天|近来|刚刚|刚才"),
        re.compile(r"\b(?:recently|currently|lately|these days|today|now|just now)\b"),
        re.compile(r"\b(?:have|has) been\b"),
    ),
    L2TemporalCue.RECURRING: (
        re.compile(r"经常|常常|反复|每(?:天|周|星期|月|年)|每隔"),
        re.compile(r"\b(?:often|frequently|repeatedly|usually|every (?:day|week|month|year))\b"),
    ),
    L2TemporalCue.STABLE: (
        re.compile(r"一直|长期|长久|多年来|这些年|始终"),
        re.compile(r"\b(?:always|long[- ]term|for years|over the years|consistently)\b"),
    ),
}


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
) -> list[str]:
    evidence_text = _normalize_evidence_text(claim.evidence_text)
    if not evidence_text:
        return []
    return [
        event.event_id
        for event, content in eligible_events
        if evidence_text in _normalize_evidence_text(content)
    ]


def phase1_claim_evidence_contract_issues(
    payload: dict[str, object],
    event_window: L2EventWindow,
) -> list[str]:
    """Describe Phase 1 claims that lack exact current-event evidence."""
    eligible_contents = [content for _event, content in _eligible_evidence_events(event_window)]
    issues: list[str] = []
    raw_claims = payload.get("fact_claims")
    if not isinstance(raw_claims, list):
        return issues
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            issues.append(f"fact_claims[{index}] must be an object")
            continue
        field_path = f"fact_claims[{index}].evidence_text"
        evidence = claim.get("evidence_text")
        if not isinstance(evidence, str) or not evidence.strip():
            issues.append(f"{field_path} is required")
        else:
            normalized_evidence = _normalize_evidence_text(evidence)
            if not any(
                normalized_evidence in _normalize_evidence_text(content)
                for content in eligible_contents
            ):
                issues.append(f"{field_path} must be an exact quote from a current message")

        temporal_path = f"fact_claims[{index}].temporal_cue"
        temporal_cue = claim.get("temporal_cue")
        if not isinstance(temporal_cue, str) or not temporal_cue.strip():
            issues.append(f"{temporal_path} is required")
        elif temporal_cue.strip().casefold() not in {cue.value for cue in L2TemporalCue}:
            issues.append(
                f"{temporal_path} must be one_off, recent, recurring, stable, or unspecified"
            )
        elif temporal_cue.strip().casefold() != L2TemporalCue.UNSPECIFIED.value:
            declared_cue = L2TemporalCue(temporal_cue.strip().casefold())
            if not isinstance(evidence, str) or declared_cue not in _temporal_cues_in_text(
                evidence
            ):
                issues.append(
                    f"{temporal_path} must be grounded in the claim's evidence_text"
                )
    return issues


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


def _temporal_cues_in_text(value: object) -> set[L2TemporalCue]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return {
        cue
        for cue, patterns in _TEMPORAL_CUE_PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    }


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


__all__ = ["ground_phase1_fact_claims", "phase1_claim_evidence_contract_issues"]
