"""Static routing table from (predicate_family, subject_scope) to allowed
evidence classes. Bridges Phase 1; replaced by QuestionClassifier in Phase 2.

The intent is to keep self-preference queries from being polluted by
Chrome-history-derived INTERESTED_IN edges (EXTERNAL_OBSERVATION).
"""

from __future__ import annotations

from typing import Literal, Optional

from ..evidence import EvidenceClass

_DECLARED = EvidenceClass.USER_SELF_REPORT.label
_OBSERVED = EvidenceClass.EXTERNAL_OBSERVATION.label


def infer_allowed_evidence_classes(
    *,
    predicate_family: Optional[str],
    subject_scope: Optional[str],
) -> Optional[set[str]]:
    """Return a hard filter set, or None if no filter should be applied."""
    if predicate_family in ("preference", "profile_fact") and subject_scope == "self":
        return {_DECLARED}
    if predicate_family == "activity":
        return {_DECLARED, _OBSERVED}
    if predicate_family == "relationship":
        return {_DECLARED, _OBSERVED}
    return None


EvidenceFocus = Literal["declared", "observed", "both"]


def classes_from_focus(focus: Optional[EvidenceFocus]) -> Optional[set[str]]:
    """Map a classifier-produced evidence_focus to an allowed_evidence_classes set.

    Returns None when focus is None — callers should fall back to the legacy
    (predicate_family, subject_scope) rule via infer_allowed_evidence_classes.
    """
    if focus == "declared":
        return {_DECLARED}
    if focus == "observed":
        return {_OBSERVED}
    if focus == "both":
        return {_DECLARED, _OBSERVED}
    return None


_OBSERVED_CUES: tuple[str, ...] = (
    "浏览", "访问", "点开", "打开", "看过", "查过",
    "browse", "browsed", "visit", "visited", "open", "opened",
    "view", "viewed", "watch", "watched",
)
_DECLARED_CUES: tuple[str, ...] = (
    "喜欢", "讨厌", "说过", "告诉", "想要", "偏好",
    "like", "dislike", "tell", "told", "say", "said",
    "prefer", "want",
)


def infer_evidence_focus_heuristic(query: str) -> Optional[EvidenceFocus]:
    """Cheap linguistic heuristic for use when no LLM refinement is available.

    Conservative: returns None on ambiguous queries so callers can fall back to
    the family/scope rule (infer_allowed_evidence_classes). Used by the rule-only
    intent decider and the service-plan augmentation path.
    """
    if not query:
        return None
    lowered = query.lower()
    has_observed = any(cue in query or cue in lowered for cue in _OBSERVED_CUES)
    has_declared = any(cue in query or cue in lowered for cue in _DECLARED_CUES)
    if has_observed and has_declared:
        return "both"
    if has_observed:
        return "observed"
    if has_declared:
        return "declared"
    return None
