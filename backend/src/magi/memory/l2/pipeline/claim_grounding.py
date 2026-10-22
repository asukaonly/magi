"""Deterministic evidence grounding for Phase 1 fact claims."""

from __future__ import annotations

import re
import unicodedata

from ..models import (
    L2BatchEvent,
    L2ClaimEvidenceMode,
    L2EventWindow,
    L2Phase1FactClaim,
    L2Phase1Result,
)
from ..phase1_models import L2AssertionMode, L2TemporalCue
from ..claim_text import claim_object_is_literal
from ..literal_grounding import grounded_literal_surface
from .claim_evidence import find_claim_evidence_occurrence

_CONTEXTUAL_CLAIM_CONFIDENCE_CAP = 0.75

def ground_phase1_fact_claims(
    phase1_result: L2Phase1Result,
    event_window: L2EventWindow,
    *,
    context_messages: list[dict[str, object]] | None = None,
) -> dict[str, int]:
    """Keep only claims grounded in exact current-window evidence."""
    eligible_events = _eligible_evidence_events(event_window)
    event_ids = {event.event_id for event, _content in eligible_events}
    context_frame = _normalized_context_frame(context_messages)
    grounded_claims: list[L2Phase1FactClaim] = []
    rejected_count = 0
    rebound_count = 0

    for claim_index, claim in enumerate(phase1_result.fact_claims, start=1):
        if claim.raw_time_expression not in claim.evidence_text:
            claim.raw_time_expression = ""
        if not claim.raw_time_expression:
            claim.calendar_expression = None
        original_event_ids = _unique_event_ids(claim.supporting_event_ids)
        valid_original_ids = [event_id for event_id in original_event_ids if event_id in event_ids]
        grounded_event_ids = _grounded_event_ids(
            claim=claim,
            eligible_events=eligible_events,
        )
        if not grounded_event_ids or _contextual_claim_rejection_reason(
            claim,
            eligible_events=eligible_events,
            grounded_event_ids=grounded_event_ids,
            context_frame=context_frame,
        ) or _literal_claim_rejection_reason(claim, context_frame):
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
    return [
        event.event_id
        for event, content in eligible_events
        if find_claim_evidence_occurrence(
            content, claim.evidence_text,
            event_type=event.event_type, source=event.source, author_type=event.author_type,
        ) is not None
    ]


def normalize_phase1_claim_contract(
    payload: dict[str, object],
    event_window: L2EventWindow,
    *,
    context_messages: list[dict[str, object]] | None = None,
) -> list[str]:
    """Normalize safe metadata and drop invalid claims without failing the batch."""
    normalizations = normalize_phase1_claim_raw_time_expressions(payload)
    raw_claims = payload.get("fact_claims")
    if not isinstance(raw_claims, list):
        return normalizations

    eligible_events = _eligible_evidence_events(event_window)
    context_frame = _normalized_context_frame(context_messages)
    kept_claims: list[dict[str, object]] = []
    rejected_count = 0
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            rejected_count += 1
            normalizations.append(f"fact_claims[{index}]: dropped non-object candidate")
            continue
        candidate = dict(claim)
        raw_cue = candidate.get("temporal_cue")
        if not isinstance(raw_cue, str) or raw_cue not in {cue.value for cue in L2TemporalCue}:
            rejected_count += 1
            normalizations.append(f"fact_claims[{index}]: dropped candidate (invalid or missing temporal_cue)")
            continue
        candidate["evidence_mode"] = (
            str(candidate.get("evidence_mode") or L2ClaimEvidenceMode.DIRECT.value)
            .strip()
            .casefold()
        )
        if not isinstance(candidate.get("supporting_event_ids"), list):
            candidate["supporting_event_ids"] = []
        if not isinstance(candidate.get("antecedent_event_ids"), list):
            candidate["antecedent_event_ids"] = []
        try:
            typed_claim = L2Phase1FactClaim.from_dict(candidate)
        except (TypeError, ValueError):
            rejected_count += 1
            normalizations.append(f"fact_claims[{index}]: dropped malformed candidate")
            continue
        missing_semantic_field = _missing_semantic_field(typed_claim)
        if missing_semantic_field is not None:
            rejected_count += 1
            normalizations.append(
                f"fact_claims[{index}]: dropped candidate " f"(missing {missing_semantic_field})"
            )
            continue
        grounded_event_ids = _grounded_event_ids(
            claim=typed_claim,
            eligible_events=eligible_events,
        )
        rejection_reason = (
            "missing exact current evidence"
            if not grounded_event_ids
            else _contextual_claim_rejection_reason(
                typed_claim,
                eligible_events=eligible_events,
                grounded_event_ids=grounded_event_ids,
                context_frame=context_frame,
            )
        )
        rejection_reason = rejection_reason or _literal_claim_rejection_reason(typed_claim, context_frame)
        if rejection_reason:
            rejected_count += 1
            normalizations.append(f"fact_claims[{index}]: dropped candidate ({rejection_reason})")
            continue
        if typed_claim.evidence_mode is not L2ClaimEvidenceMode.DIRECT:
            candidate["confidence"] = min(
                float(typed_claim.confidence),
                _CONTEXTUAL_CLAIM_CONFIDENCE_CAP,
            )
        kept_claims.append(candidate)

    payload["fact_claims"] = kept_claims
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        payload["diagnostics"] = diagnostics
    diagnostics["rejected_fact_claim_count"] = rejected_count
    return normalizations


def _missing_semantic_field(claim: L2Phase1FactClaim) -> str | None:
    required = {
        "subject_ref": claim.subject_ref,
        "predicate": claim.predicate,
        "object_ref": claim.object_ref,
        "object_type": claim.object_type,
        "fact_kind": getattr(claim.fact_kind, "value", claim.fact_kind),
        "polarity": claim.polarity,
        "specificity": claim.specificity,
    }
    return next(
        (field_name for field_name, value in required.items() if not str(value or "").strip()),
        None,
    )


def normalize_phase1_claim_raw_time_expressions(
    payload: dict[str, object],
) -> list[str]:
    """Keep only raw time expressions copied exactly from Claim evidence."""

    raw_claims = payload.get("fact_claims")
    if not isinstance(raw_claims, list):
        return []
    normalizations: list[str] = []
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            continue
        raw = claim.get("raw_time_expression")
        expression = raw if isinstance(raw, str) else ""
        evidence = claim.get("evidence_text")
        evidence_text = evidence if isinstance(evidence, str) else ""
        if expression and expression in evidence_text:
            continue
        claim["raw_time_expression"] = ""
        claim["calendar_expression"] = None
        if expression:
            normalizations.append(
                f"fact_claims[{index}].raw_time_expression: rejected non-evidence substring"
            )
    return normalizations


def _contextual_claim_rejection_reason(
    claim: L2Phase1FactClaim,
    *,
    eligible_events: list[tuple[L2BatchEvent, str]],
    grounded_event_ids: list[str],
    context_frame: list[dict[str, object]],
) -> str | None:
    if claim.assertion_mode is not L2AssertionMode.ASSERTED:
        return f"non_asserted_proposition:{claim.assertion_mode.value}"
    mode = L2ClaimEvidenceMode.from_value(claim.evidence_mode)
    antecedent_ids = _unique_event_ids(claim.antecedent_event_ids)
    if mode is L2ClaimEvidenceMode.DIRECT:
        if antecedent_ids:
            return "direct claim cites context"
        claim.antecedent_event_ids = []
        return None

    grounded_by_user = any(
        event.event_id in grounded_event_ids
        and str(event.author_type or "").strip().casefold() == "user"
        for event, _content in eligible_events
    )
    if not grounded_by_user:
        return "contextual claim lacks current user authority"

    if mode is L2ClaimEvidenceMode.CONFIRMATION:
        required_ids = _required_confirmation_antecedent_ids(context_frame)
        if not required_ids or antecedent_ids != required_ids:
            return "confirmation does not cite the immediate assistant message"
    else:
        required_ids = _required_clarification_antecedent_ids(context_frame)
        if not required_ids or antecedent_ids != required_ids:
            return "clarification does not cite the immediate context frame"
        if len(_normalize_evidence_text(claim.evidence_text)) > 200:
            return "clarification is not a short reply"

    claim.antecedent_event_ids = required_ids
    claim.confidence = min(claim.confidence, _CONTEXTUAL_CLAIM_CONFIDENCE_CAP)
    return None


def _literal_claim_rejection_reason(
    claim: L2Phase1FactClaim,
    context_frame: list[dict[str, object]],
) -> str | None:
    if not claim_object_is_literal(claim.predicate):
        return None
    sources = [claim.evidence_text]
    if claim.evidence_mode is not L2ClaimEvidenceMode.DIRECT:
        antecedent_ids = set(claim.antecedent_event_ids)
        sources.extend(
            str(message["content"])
            for message in context_frame
            if message["event_id"] in antecedent_ids
        )
    if grounded_literal_surface(claim.predicate, claim.object_ref, sources) is None:
        return "literal value lacks authorized evidence"
    return None


def _normalized_context_frame(
    context_messages: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    frame: list[dict[str, object]] = []
    for message in context_messages or []:
        event_id = str(message.get("event_id") or "").strip()
        content = str(message.get("content") or "").strip()
        role = str(message.get("role") or message.get("author_type") or "").strip().casefold()
        if not event_id or not content or role not in {"assistant", "user"}:
            continue
        frame.append(
            {
                "event_id": event_id,
                "role": role,
                "content": content,
                "session_seq": message.get("session_seq"),
                "timestamp": message.get("timestamp"),
            }
        )
    return frame[-3:]


def _required_confirmation_antecedent_ids(
    context_frame: list[dict[str, object]],
) -> list[str]:
    if not context_frame or context_frame[-1]["role"] != "assistant":
        return []
    return [str(context_frame[-1]["event_id"])]


def _required_clarification_antecedent_ids(
    context_frame: list[dict[str, object]],
) -> list[str]:
    if not context_frame:
        return []
    last_message = context_frame[-1]
    if last_message["role"] == "user":
        return [str(last_message["event_id"])]
    if last_message["role"] != "assistant":
        return []
    prior_user = next(
        (message for message in reversed(context_frame[:-1]) if message["role"] == "user"),
        None,
    )
    if prior_user is None:
        return []
    return [str(prior_user["event_id"]), str(last_message["event_id"])]


def _eligible_evidence_events(
    event_window: L2EventWindow,
) -> list[tuple[L2BatchEvent, str]]:
    return [
        (event, event.content)
        for event in event_window.events
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


__all__ = [
    "ground_phase1_fact_claims",
    "normalize_phase1_claim_contract",
    "normalize_phase1_claim_raw_time_expressions",
]
