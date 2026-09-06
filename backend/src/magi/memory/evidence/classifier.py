"""Deterministic evidence classification for memory governance.

The classifier is intentionally a small, ordered table of declarative rules
matched against a normalized ``ClassificationContext``. Each rule has a
stable ``name`` which is surfaced as ``EvidenceClassification.reason_code``,
so the wire-level provenance for "why was this event placed in this
evidence class" stays one-to-one with the rule that fired.

Adding a new evidence class should normally mean:

* add the enum value and label in ``models.py``,
* add a ``PolicyDecision`` row in ``policy.py``,
* add a new ``EvidenceRule`` entry to ``EVIDENCE_RULES`` below.

Nothing else in this module needs to change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ...events.first_context import FIRST_CONTEXT_STORY_INTERACTION_KIND
from ...events.recall_feedback import RECALL_FEEDBACK_INTERACTION_KIND
from ..event_contracts import MemoryDomain, MemoryEvent
from .models import EvidenceClass, EvidenceClassification

# Sentence-final question markers in common locales.
_QUESTION_MARK_CHARS = ("?", "？")

# Leading interrogative tokens. Matched case-insensitively against the first
# whitespace-separated token (Latin scripts) or character window (CJK scripts).
# Only stable, low-ambiguity markers are listed; ambiguous tokens like ``is``,
# ``do``, ``have`` intentionally stay out so that statements like
# ``"I have a cat"`` remain classified as ``user_self_report``.
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

# Strong interrogatives that signal a question wherever they appear. Kept to
# low-ambiguity tokens; "什么 / 哪 / 谁" are intentionally NOT here (they have
# common non-question idioms) and are handled by the clause-end rule instead.
_QUESTION_WORD_ANYWHERE_CJK = (
    "怎么",
    "怎样",
    "为什么",
    "为何",
    "如何",
    "多少",
    "多久",
    "几时",
    "几点",
    "哪里",
    "哪儿",
)

# Interrogatives detected ONLY at the clause end — words the anywhere-rule
# deliberately omits (什么/哪/谁 have non-question idioms) plus 几个. Anything
# already in _QUESTION_WORD_ANYWHERE_CJK is intentionally NOT repeated here.
_QUESTION_TAIL_WORD_CJK = ("什么", "哪", "谁", "几个")

# Trailing mood particles / punctuation stripped before the clause-end check,
# so "...在看什么呀" still ends on the interrogative "什么".
_TRAILING_MOOD_CHARS = "呀啊呗啦哈哦噢吧呢嘛~。.!！ "

# Idioms where an interrogative token is NOT a question. First-match wins, so
# these veto the recall-favoring rules above.
_NON_QUESTION_CONTEXT_CJK = (
    "没什么",
    "什么都",
    "啥都",
    "没怎么",
    "不怎么",
    "怎么都",
    "怎么也",
    "谁都",
    "谁也",
    "知道为什么",
    "不知道为什么",
    "知道怎么",
    "不知道怎么",
    "不知怎么",
    "哪里哪里",  # modesty reply ("哪里哪里，您过奖了"), not a location question
)

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
_LEADING_TRIM_CHARS = "\"'`“”‘’（(《<【 "
_FIRST_CONTEXT_LOW_SIGNAL_VALUES = {
    "-",
    "--",
    "...",
    "asdf",
    "idk",
    "n/a",
    "none",
    "null",
    "qwer",
    "test",
    "xxx",
    "zxcv",
    "不知道",
    "无",
    "没什么",
    "随便",
}
_CLAUSE_SPLIT_RE = re.compile(r"[，,。；;！？!?]+")
_HISTORY_IMPORT_DOCUMENT_EVENT_TYPE = "history_import.document"
_HISTORY_IMPORT_CHAT_EVENT_TYPE = "history_import.chat"
_HISTORY_IMPORT_SOURCE = "history_import"


@dataclass(frozen=True)
class _ClassificationContext:
    """Normalized facts that rules match against.

    Encapsulates the small amount of pre-computation (lowercasing, trimming,
    grounding type derivation) so each rule body is a one-liner.
    """

    event: MemoryEvent
    author_role: str | None
    grounding_type: str | None
    semantic_owner: str | None
    content_type: str | None
    memory_domain: MemoryDomain
    interaction_kind: str | None
    user_intent: str | None  # "question" | "request" | None, only computed for user
    user_authored_history: bool
    first_context_low_signal: bool
    first_context_has_self_report: bool


@dataclass(frozen=True)
class _EvidenceRule:
    """One declarative classification rule.

    ``name`` becomes the ``reason_code`` on the resulting classification, so
    keep it stable across releases (it is part of the observability /
    backfill contract).
    """

    name: str
    evidence_class: EvidenceClass
    matches: Callable[[_ClassificationContext], bool]


def _is_user(ctx: _ClassificationContext) -> bool:
    return ctx.author_role == "user"


def _is_assistant(ctx: _ClassificationContext) -> bool:
    return ctx.author_role == "assistant"


# Ordered list of evidence rules. First match wins.
#
# Order matters: ``runtime_chat_response_action`` precedes ``runtime_domain``
# because an ``ActionExecuted`` wrapping ``ChatResponseAction`` has
# ``memory_domain=runtime_telemetry`` but should be treated as assistant
# speech (with retrieval scope ``conversation_only``), not as audit-only
# runtime telemetry.
EVIDENCE_RULES: tuple[_EvidenceRule, ...] = (
    _EvidenceRule(
        name="runtime_chat_response_action",
        evidence_class=EvidenceClass.ASSISTANT_RUNTIME_DERIVATION,
        matches=lambda ctx: _is_assistant(ctx) and ctx.content_type == "runtime_derivation",
    ),
    _EvidenceRule(
        name="runtime_domain",
        evidence_class=EvidenceClass.SYSTEM_RUNTIME,
        matches=lambda ctx: ctx.memory_domain == MemoryDomain.RUNTIME_TELEMETRY
        or ctx.author_role == "system",
    ),
    _EvidenceRule(
        name="external_source",
        evidence_class=EvidenceClass.EXTERNAL_OBSERVATION,
        matches=lambda ctx: ctx.author_role in {"external", "source"},
    ),
    _EvidenceRule(
        name="user_authored_history_archive",
        evidence_class=EvidenceClass.USER_SELF_REPORT,
        matches=lambda ctx: ctx.user_authored_history,
    ),
    _EvidenceRule(
        name="user_recall_feedback_interaction",
        evidence_class=EvidenceClass.USER_REQUEST,
        matches=lambda ctx: _is_user(ctx)
        and ctx.interaction_kind == RECALL_FEEDBACK_INTERACTION_KIND,
    ),
    _EvidenceRule(
        name="assistant_content_type",
        evidence_class=EvidenceClass.ASSISTANT_TOOL_GROUNDED,
        matches=lambda ctx: _is_assistant(ctx) and ctx.content_type == "tool_result",
    ),
    _EvidenceRule(
        name="first_context_story_low_signal",
        evidence_class=EvidenceClass.USER_REQUEST,
        matches=lambda ctx: _is_user(ctx) and ctx.first_context_low_signal,
    ),
    _EvidenceRule(
        name="first_context_story_with_self_report",
        evidence_class=EvidenceClass.USER_SELF_REPORT,
        matches=lambda ctx: _is_user(ctx) and ctx.first_context_has_self_report,
    ),
    _EvidenceRule(
        name="user_question_lead_or_mark",
        evidence_class=EvidenceClass.USER_QUESTION,
        matches=lambda ctx: _is_user(ctx) and ctx.user_intent == "question",
    ),
    _EvidenceRule(
        name="user_request_imperative_lead",
        evidence_class=EvidenceClass.USER_REQUEST,
        matches=lambda ctx: _is_user(ctx) and ctx.user_intent == "request",
    ),
    _EvidenceRule(
        name="user_default",
        evidence_class=EvidenceClass.USER_SELF_REPORT,
        matches=_is_user,
    ),
    _EvidenceRule(
        name="assistant_default",
        evidence_class=EvidenceClass.ASSISTANT_FREEFORM,
        matches=_is_assistant,
    ),
)


def classify_event_evidence(event: MemoryEvent) -> EvidenceClassification:
    """Classify a normalized event into an evidence class.

    The decision is a first-match scan of ``EVIDENCE_RULES``. When no rule
    fires (a degenerate event with an unrecognized author role and a
    non-runtime memory domain), the fallback is ``external_observation``
    with ``reason_code='fallback_external'`` so audit pipelines can spot
    the gap without raising.
    """
    ctx = _build_context(event)
    for rule in EVIDENCE_RULES:
        if rule.matches(ctx):
            return _build_classification(
                rule.evidence_class,
                reason_code=rule.name,
                ctx=ctx,
            )
    return _build_classification(
        EvidenceClass.EXTERNAL_OBSERVATION,
        reason_code="fallback_external",
        ctx=ctx,
    )


def _build_context(event: MemoryEvent) -> _ClassificationContext:
    author_role = _normalized(event.author_type)
    content_type = _normalized(event.content_type)
    metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
    user_intent = _detect_user_intent(event.content) if author_role == "user" else None
    interaction_kind = _normalized(metadata.get("interaction_kind"))
    is_first_context = interaction_kind == FIRST_CONTEXT_STORY_INTERACTION_KIND
    return _ClassificationContext(
        event=event,
        author_role=author_role,
        grounding_type=_grounding_type(event, author_role, content_type),
        semantic_owner=_semantic_owner(author_role),
        content_type=content_type,
        memory_domain=event.memory_domain,
        interaction_kind=interaction_kind,
        user_intent=user_intent,
        user_authored_history=_is_user_authored_history(
            event,
            metadata=metadata,
            author_role=author_role,
        ),
        first_context_low_signal=(
            bool(is_first_context and _is_first_context_low_signal(event.content))
        ),
        first_context_has_self_report=(
            bool(is_first_context and _has_first_context_self_report_clause(event.content))
        ),
    )


def _is_user_authored_history(
    event: MemoryEvent,
    *,
    metadata: dict[str, object],
    author_role: str | None,
) -> bool:
    history_import = metadata.get("history_import")
    history_metadata = history_import if isinstance(history_import, dict) else {}
    return bool(
        author_role == "user"
        and event.memory_domain == MemoryDomain.USER_AUTHORED
        and _normalized(event.source) == _HISTORY_IMPORT_SOURCE
        and _normalized(event.event_type)
        in {_HISTORY_IMPORT_DOCUMENT_EVENT_TYPE, _HISTORY_IMPORT_CHAT_EVENT_TYPE}
        and history_metadata.get("historical") is True
    )


def _build_classification(
    evidence_class: EvidenceClass,
    *,
    reason_code: str,
    ctx: _ClassificationContext,
) -> EvidenceClassification:
    return EvidenceClassification(
        evidence_class=evidence_class.label,
        reason_code=reason_code,
        speaker_role=ctx.author_role,
        grounding_type=ctx.grounding_type,
        semantic_owner=ctx.semantic_owner,
        originality_type="primary",
        source_event_ids=[],
    )


def _grounding_type(
    event: MemoryEvent,
    author_role: str | None,
    content_type: str | None,
) -> str | None:
    if author_role == "user":
        return "self_reported"
    if author_role == "assistant":
        if content_type == "tool_result":
            return "tool_grounded"
        if content_type == "runtime_derivation":
            return "runtime_derived"
        return "freeform_generated"
    if event.memory_domain == MemoryDomain.RUNTIME_TELEMETRY or author_role == "system":
        return "observed"
    if author_role in {"external", "source", "tool"}:
        return "observed"
    return "observed"


def _semantic_owner(author_role: str | None) -> str | None:
    if author_role == "user":
        return "user"
    if author_role == "assistant":
        return "assistant"
    if author_role in {"external", "source", "system", "tool"}:
        return "world"
    return None


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


_SELF_STATEMENT = re.compile(r"(?:我|本人|\bI\b|\bmy\b)", re.IGNORECASE)
_NON_ASSERTION = re.compile(
    r"^(?:假如|假设|如果|要是|例如|比如|他(?:说|问)|她(?:说|问)|据说|以下.{0,8}(?:引用|示例)|"
    r"if\b|suppose\b|imagine\b|for example\b)|(?:他说|她说|said|says)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_QUOTED_SPAN = re.compile(r'"[^"\n]*"|“[^”]*”|‘[^’]*’|`[^`]*`')


def asserted_evidence_clauses(content: str | None) -> list[str]:
    """Return statement clauses while preserving question marks and quote scope."""
    text = str(content or "")
    text = _QUOTED_SPAN.sub(
        lambda match: " " * len(match.group()) if _SELF_STATEMENT.search(match.group()) else match.group(),
        text,
    )
    clauses = re.findall(r"[^，,。；;！？!?\n]+[，,。；;！？!?]?", text)
    runs: list[str] = []
    current: list[str] = []
    hypothetical = False
    for raw_clause in clauses:
        clause = raw_clause.strip()
        hypothetical = hypothetical or bool(_NON_ASSERTION.search(clause))
        asserted = (
            bool(clause)
            and not hypothetical
            and not clause.startswith((">", "```", "~~~"))
            and _detect_clause_intent(clause.rstrip("，,；;")) is None
        )
        if asserted:
            current.append(clause)
        elif current:
            runs.append("".join(current))
            current = []
        if clause.endswith(("。", "！", "!", "？", "?", ".")):
            hypothetical = False
    if current:
        runs.append("".join(current))
    return runs


def _detect_user_intent(content: str | None) -> str | None:
    if any(_SELF_STATEMENT.search(clause) for clause in asserted_evidence_clauses(content)):
        return None
    return _detect_clause_intent(content)


def _detect_clause_intent(content: str | None) -> str | None:
    """Heuristically detect whether a user message is a question or request.

    Returns ``"question"``, ``"request"``, or ``None`` (treat as
    ``user_self_report``). Detection intentionally favors specificity over
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

    head = text.lstrip(_LEADING_TRIM_CHARS)
    if not head:
        return None
    head_lower = head.lower()

    first_token_match = _WHITESPACE_RE.split(head_lower, maxsplit=1)
    first_token = first_token_match[0] if first_token_match else ""
    first_token = first_token.rstrip(",.;:!?")
    if first_token in _QUESTION_LEAD_LATIN:
        return "question"

    is_non_question_context = any(ctx_idiom in text for ctx_idiom in _NON_QUESTION_CONTEXT_CJK)

    if not is_non_question_context and any(head.startswith(lead) for lead in _QUESTION_LEAD_CJK):
        return "question"

    if any(text.endswith(tail) or text.endswith(tail + "。") for tail in _QUESTION_TAIL_CJK):
        return "question"

    if not is_non_question_context:
        if any(word in text for word in _QUESTION_WORD_ANYWHERE_CJK):
            return "question"
        tail_trimmed = text.rstrip(_TRAILING_MOOD_CHARS + "".join(_QUESTION_MARK_CHARS))
        if any(tail_trimmed.endswith(word) for word in _QUESTION_TAIL_WORD_CJK):
            return "question"

    if any(head_lower.startswith(lead) for lead in _REQUEST_LEAD_LATIN):
        return "request"
    if any(head.startswith(lead) for lead in _REQUEST_LEAD_CJK):
        return "request"

    return None


def _is_first_context_low_signal(content: str | None) -> bool:
    text = str(content or "").strip().lower()
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if compact in _FIRST_CONTEXT_LOW_SIGNAL_VALUES:
        return True
    if re.fullmatch(r"\d+", compact):
        return True
    if re.fullmatch(r"(?:asdf|qwer(?:ty)?|zxcv(?:bn)?)[a-z]*", compact):
        return True
    if len(compact) >= 3 and len(set(compact)) == 1:
        return True
    return False


def _has_first_context_self_report_clause(content: str | None) -> bool:
    for raw_clause in _CLAUSE_SPLIT_RE.split(str(content or "")):
        clause = raw_clause.strip()
        if not clause:
            continue
        if _detect_user_intent(clause) is None and not _is_first_context_low_signal(clause):
            return True
    return False


__all__ = ["EvidenceClassification", "classify_event_evidence"]
