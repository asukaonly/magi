"""Deterministic evidence classification for memory governance."""

from __future__ import annotations

import re

from ..event_contracts import MemoryDomain, MemoryEvent
from .models import EvidenceClass, EvidenceClassification

_EXTERNAL_SOURCES = {"timeline", "sensor", "calendar", "location", "external_feed", "external"}

# Sentence-final question markers in common locales.
_QUESTION_MARK_CHARS = ("?", "？")

# Leading interrogative tokens. Matched case-insensitively against the first
# whitespace-separated token (Latin scripts) or character window (CJK scripts).
# Only stable, low-ambiguity markers are listed; ambiguous tokens like "is",
# "do", "have" intentionally stay out so that statements like "I have a cat"
# remain classified as user_self_report.
_QUESTION_LEAD_LATIN = (
    "what",
    "why",
    "how",
    "who",
    "whom",
    "whose",
    "where",
    "when",
    "which",
)
_QUESTION_LEAD_CJK = (
    "什么",
    "为什么",
    "为何",
    "怎么",
    "怎样",
    "如何",
    "哪",
    "谁",
    "几时",
    "多少",
    "多久",
    "能否",
    "是否",
    "可否",
)
_QUESTION_TAIL_CJK = ("吗", "呢", "嘛")

# Imperative leads that mark user requests/commands rather than self-reports.
_REQUEST_LEAD_LATIN = (
    "please",
    "pls",
    "kindly",
    "help me",
    "let me",
    "let's",
    "show me",
    "tell me",
    "give me",
    "send me",
    "find me",
    "can you",
    "could you",
    "would you",
    "will you",
)
_REQUEST_LEAD_CJK = (
    "请",
    "麻烦",
    "帮我",
    "帮个忙",
    "帮忙",
    "给我",
    "告诉我",
    "教我",
    "替我",
    "让我",
    "麻烦你",
)

_WHITESPACE_RE = re.compile(r"\s+")


def classify_event_evidence(event: MemoryEvent) -> EvidenceClassification:
    """Classify a normalized event into an evidence class."""

    speaker_role = _normalized(event.author_type)
    grounding_type = _grounding_type(event, speaker_role)
    semantic_owner = _semantic_owner(speaker_role)
    originality_type = "primary"
    source_event_ids: list[str] = []
    normalized_source = _normalized(event.source)

    if _is_assistant_runtime_derivation(event):
        return EvidenceClassification(
            evidence_class=EvidenceClass.ASSISTANT_RUNTIME_DERIVATION.label,
            reason_code="runtime_chat_response_action",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if event.memory_domain == MemoryDomain.RUNTIME_TELEMETRY or speaker_role == "system":
        return EvidenceClassification(
            evidence_class=EvidenceClass.SYSTEM_RUNTIME.label,
            reason_code="runtime_domain",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role in {"external", "sensor"} or normalized_source in _EXTERNAL_SOURCES:
        return EvidenceClassification(
            evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
            reason_code="external_source",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "assistant" and grounding_type == "tool_grounded":
        return EvidenceClassification(
            evidence_class=EvidenceClass.ASSISTANT_TOOL_GROUNDED.label,
            reason_code="assistant_content_type",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "assistant":
        return EvidenceClassification(
            evidence_class=EvidenceClass.ASSISTANT_FREEFORM.label,
            reason_code="assistant_default",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    if speaker_role == "user":
        user_intent = _detect_user_intent(event.content)
        if user_intent == "question":
            return EvidenceClassification(
                evidence_class=EvidenceClass.USER_QUESTION.label,
                reason_code="user_question_lead_or_mark",
                speaker_role=speaker_role,
                grounding_type=grounding_type,
                semantic_owner=semantic_owner,
                originality_type=originality_type,
                source_event_ids=source_event_ids,
            )
        if user_intent == "request":
            return EvidenceClassification(
                evidence_class=EvidenceClass.USER_REQUEST.label,
                reason_code="user_request_imperative_lead",
                speaker_role=speaker_role,
                grounding_type=grounding_type,
                semantic_owner=semantic_owner,
                originality_type=originality_type,
                source_event_ids=source_event_ids,
            )
        return EvidenceClassification(
            evidence_class=EvidenceClass.USER_SELF_REPORT.label,
            reason_code="user_default",
            speaker_role=speaker_role,
            grounding_type=grounding_type,
            semantic_owner=semantic_owner,
            originality_type=originality_type,
            source_event_ids=source_event_ids,
        )

    return EvidenceClassification(
        evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
        reason_code="fallback_external",
        speaker_role=speaker_role,
        grounding_type=grounding_type,
        semantic_owner=semantic_owner,
        originality_type=originality_type,
        source_event_ids=source_event_ids,
    )


def _grounding_type(event: MemoryEvent, speaker_role: str | None) -> str | None:
    if speaker_role == "user":
        return "self_reported"
    if speaker_role == "assistant":
        return "tool_grounded" if _normalized(event.content_type) == "tool_result" else "freeform_generated"
    if event.memory_domain == MemoryDomain.RUNTIME_TELEMETRY or speaker_role == "system":
        return "observed"
    if speaker_role in {"external", "sensor", "tool"}:
        return "observed"
    return "observed"


def _semantic_owner(speaker_role: str | None) -> str | None:
    if speaker_role == "user":
        return "user"
    if speaker_role == "assistant":
        return "assistant"
    if speaker_role in {"external", "sensor", "system", "tool"}:
        return "world"
    return None


def _is_assistant_runtime_derivation(event: MemoryEvent) -> bool:
    if str(event.event_type).strip() != "ActionExecuted":
        return False
    if _normalized(event.source) != "runtime_event_emitter":
        return False
    return _normalized(event.source_item_id) == "chatresponseaction"


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _detect_user_intent(content: str | None) -> str | None:
    """Heuristically detect whether a user message is a question or request.

    Returns ``"question"``, ``"request"``, or ``None`` (treat as
    user_self_report). Detection intentionally favors specificity over
    recall so that ordinary user statements such as ``"I have a cat"`` keep
    flowing through ``user_self_report``; only sentences with a clear
    interrogative marker or an explicit imperative lead are reclassified.
    """
    if not content:
        return None
    text = str(content).strip()
    if not text:
        return None

    if text.endswith(_QUESTION_MARK_CHARS):
        return "question"

    # Trim leading punctuation/quotes/spaces before head matching.
    leading_strip = "\"'`“”‘’（(《<【 "
    head = text.lstrip(leading_strip)
    if not head:
        return None
    head_lower = head.lower()

    # Latin first-token interrogative.
    first_token_match = _WHITESPACE_RE.split(head_lower, maxsplit=1)
    first_token = first_token_match[0] if first_token_match else ""
    first_token = first_token.rstrip(",.;:!?")
    if first_token in _QUESTION_LEAD_LATIN:
        return "question"

    if any(head.startswith(lead) for lead in _QUESTION_LEAD_CJK):
        return "question"

    # CJK final particles that strongly imply a yes/no question.
    if any(text.endswith(tail) or text.endswith(tail + "。") for tail in _QUESTION_TAIL_CJK):
        return "question"

    # Imperative leads (request/command).
    if any(head_lower.startswith(lead) for lead in _REQUEST_LEAD_LATIN):
        return "request"
    if any(head.startswith(lead) for lead in _REQUEST_LEAD_CJK):
        return "request"

    return None


__all__ = ["EvidenceClassification", "classify_event_evidence"]