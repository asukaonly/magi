"""Map explicit semantic evidence intent to deterministic storage constraints."""
from __future__ import annotations
from typing import Literal, Optional
from ..evidence import EvidenceClass
_DECLARED = EvidenceClass.USER_SELF_REPORT.label
_OBSERVED = EvidenceClass.EXTERNAL_OBSERVATION.label
EvidenceFocus = Literal["declared", "observed", "both"]

def classes_from_focus(focus: Optional[EvidenceFocus]) -> Optional[set[str]]:
    """Map a classifier-produced evidence_focus to an allowed_evidence_classes set.

    Unknown intent adds no evidence-class restriction. Governance remains mandatory.
    """
    if focus == "declared":
        return {_DECLARED}
    if focus == "observed":
        return {_OBSERVED}
    if focus == "both":
        return {_DECLARED, _OBSERVED}
    return None
