"""Evidence-class policy consumes typed intent, never natural-language cues."""
import pytest
from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.evidence_routing import classes_from_focus

@pytest.mark.parametrize(("focus", "expected"), [
    ("declared", {EvidenceClass.USER_SELF_REPORT.label}),
    ("observed", {EvidenceClass.EXTERNAL_OBSERVATION.label}),
    ("both", {EvidenceClass.USER_SELF_REPORT.label, EvidenceClass.EXTERNAL_OBSERVATION.label}),
    (None, None),
])
def test_typed_evidence_focus(focus, expected):
    assert classes_from_focus(focus) == expected
