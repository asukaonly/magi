"""Deterministic evidence grounding for Phase 1 fact claims."""

from __future__ import annotations

import re
import unicodedata

from ...evidence.classifier import asserted_evidence_clauses
from ..models import (
    L2BatchEvent,
    L2ClaimEvidenceMode,
    L2EventWindow,
    L2Phase1FactClaim,
    L2Phase1Result,
)
from ..phase1_models import L2TemporalCue
from .history_markdown import (
    HISTORY_DOCUMENT_EVENT_TYPE,
    find_history_document_author_occurrence,
)

_CONTEXTUAL_CLAIM_CONFIDENCE_CAP = 0.75
_EXPLICIT_CONFIRMATIONS = frozenset(
    {
        "yes",
        "no",
        "correct",
        "exactly",
        "right",
        "true",
        "是",
        "是的",
        "对",
        "对的",
        "没错",
        "就是",
        "确定",
        "当然",
        "不是",
        "不对",
        "没有",
    }
)

_TEMPORAL_CUE_PATTERNS: dict[L2TemporalCue, tuple[re.Pattern[str], ...]] = {
    L2TemporalCue.ONE_OFF: (
        re.compile(r"昨晚|昨天|今天|今早|今晚|(?:^|[，,。])(?:早饭|午饭|晚饭|早餐|午餐|晚餐)(?:吃|是|后|时)|这顿|那顿|这一次|这次|比上次|刚刚|刚才|只.{0,4}一次|首次|第一次|最后一次"),
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
_TEMPORAL_CUE_PRECEDENCE = (
    L2TemporalCue.ONE_OFF,
    L2TemporalCue.RECENT,
    L2TemporalCue.RECURRING,
    L2TemporalCue.STABLE,
)


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
        ):
            rejected_count += 1
            continue
        if grounded_event_ids != valid_original_ids and original_event_ids:
            rebound_count += 1
        claim.supporting_event_ids = grounded_event_ids
        preference = claim.to_dict()
        _normalize_preference_scope(preference)
        claim.temporal_cue = L2TemporalCue.from_value(preference["temporal_cue"])
        claim.fact_kind = type(claim.fact_kind).from_value(preference["fact_kind"])
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
        if _event_has_grounded_evidence_occurrence(
            event=event,
            content=content,
            normalized_evidence_text=evidence_text,
            raw_evidence_text=claim.evidence_text,
        )
    ]


def _event_has_grounded_evidence_occurrence(
    *,
    event: L2BatchEvent,
    content: str,
    normalized_evidence_text: str,
    raw_evidence_text: str,
) -> bool:
    if event.event_type != HISTORY_DOCUMENT_EVENT_TYPE:
        if str(event.author_type or "").casefold() == "user":
            return any(
                normalized_evidence_text in _normalize_evidence_text(clause)
                for clause in asserted_evidence_clauses(content)
            )
        return normalized_evidence_text in _normalize_evidence_text(content)
    return find_history_document_author_occurrence(content, raw_evidence_text) is not None


def normalize_phase1_claim_contract(
    payload: dict[str, object],
    event_window: L2EventWindow,
    *,
    context_messages: list[dict[str, object]] | None = None,
) -> list[str]:
    """Normalize safe metadata and drop invalid claims without failing the batch."""
    normalizations = normalize_phase1_claim_temporal_cues(payload)
    normalizations.extend(normalize_phase1_claim_raw_time_expressions(payload))
    for raw_claim in payload.get("fact_claims", []) if isinstance(payload.get("fact_claims"), list) else []:
        if isinstance(raw_claim, dict):
            _normalize_preference_scope(raw_claim)
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


_DIRECT_PREFERENCE = re.compile(
    r"(?:我|本人)(?:很|好|太|挺|超级|尤其|非常|特别|比较|更|最|不|并不|一点|一直|平时|通常|最近|长期|现在|还是|也|真的){0,4}(?:喜欢|讨厌|偏爱|爱吃|爱喝|不爱)|"
    r"^(?:喜欢|讨厌|偏爱|爱吃|爱喝)|\bI\s+(?:(?:really|always|usually|recently|still|do\s+not|don't)\s+)*(?:like|love|prefer|hate|dislike)\b",
    re.IGNORECASE,
)


def _normalize_preference_scope(claim: dict[str, object]) -> None:
    """Separate a direct preference from an evaluation of one experience."""
    if str(claim.get("predicate") or "").upper() not in {"LIKES", "DISLIKES"}:
        return
    evidence = str(claim.get("evidence_text") or "")
    cues = _temporal_cues_in_text(evidence)
    if L2TemporalCue.ONE_OFF in cues or not _DIRECT_PREFERENCE.search(evidence):
        claim["temporal_cue"] = L2TemporalCue.ONE_OFF.value
        claim["fact_kind"] = "explicit_fact"
        return
    claim["fact_kind"] = "stable_preference"
    if L2TemporalCue.RECENT in cues:
        claim["temporal_cue"] = L2TemporalCue.RECENT.value


def normalize_phase1_claim_temporal_cues(
    payload: dict[str, object],
) -> list[str]:
    """Derive explicit temporal cues or default them without discarding claims."""
    raw_claims = payload.get("fact_claims")
    if not isinstance(raw_claims, list):
        return []

    valid_cues = {cue.value for cue in L2TemporalCue}
    normalizations: list[str] = []
    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            continue
        raw_cue = claim.get("temporal_cue")
        normalized_cue = raw_cue.strip().casefold() if isinstance(raw_cue, str) else ""
        evidence = claim.get("evidence_text")
        grounded_cues = _temporal_cues_in_text(evidence) if isinstance(evidence, str) else set()
        if normalized_cue in valid_cues and (
            L2TemporalCue(normalized_cue) in grounded_cues
            or (normalized_cue == L2TemporalCue.UNSPECIFIED.value and not grounded_cues)
        ):
            claim["temporal_cue"] = normalized_cue
            continue

        if raw_cue is None or (isinstance(raw_cue, str) and not raw_cue.strip()):
            previous = "missing"
        elif normalized_cue in valid_cues:
            previous = normalized_cue
        else:
            previous = "invalid"
        corrected_cue = next(
            (cue for cue in _TEMPORAL_CUE_PRECEDENCE if cue in grounded_cues),
            L2TemporalCue.UNSPECIFIED,
        )
        claim["temporal_cue"] = corrected_cue.value
        normalizations.append(
            f"fact_claims[{index}].temporal_cue: {previous} -> {corrected_cue.value}"
        )
    return normalizations


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
        if not _is_explicit_confirmation(claim.evidence_text):
            return "confirmation is ambiguous"
    else:
        required_ids = _required_clarification_antecedent_ids(context_frame)
        if not required_ids or antecedent_ids != required_ids:
            return "clarification does not cite the immediate context frame"
        if len(_normalize_evidence_text(claim.evidence_text)) > 200:
            return "clarification is not a short reply"

    claim.antecedent_event_ids = required_ids
    claim.confidence = min(claim.confidence, _CONTEXTUAL_CLAIM_CONFIDENCE_CAP)
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


def _is_explicit_confirmation(value: object) -> bool:
    normalized = _normalize_evidence_text(value)
    normalized = normalized.strip(".,!?;:，。！？；：")
    return normalized in _EXPLICIT_CONFIRMATIONS


def _eligible_evidence_events(
    event_window: L2EventWindow,
) -> list[tuple[L2BatchEvent, str]]:
    events = list(event_window.events)
    window_texts = list(event_window.texts)
    texts_are_aligned = len(window_texts) == len(events)
    return [
        (
            event,
            event.content
            if event.event_type == HISTORY_DOCUMENT_EVENT_TYPE or not texts_are_aligned
            else window_texts[index],
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


__all__ = [
    "ground_phase1_fact_claims",
    "normalize_phase1_claim_contract",
    "normalize_phase1_claim_temporal_cues",
    "normalize_phase1_claim_raw_time_expressions",
]
