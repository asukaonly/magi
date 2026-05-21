"""Static routing table from (predicate_family, subject_scope) to allowed
evidence classes. Bridges Phase 1; replaced by QuestionClassifier in Phase 2.

The intent is to keep self-preference queries from being polluted by
Chrome-history-derived INTERESTED_IN edges (EXTERNAL_OBSERVATION).
"""

from __future__ import annotations

from typing import Optional

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
