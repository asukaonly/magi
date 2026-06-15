"""Tests for AssertionScope.INTEREST and its assignment to EXTERNAL_OBSERVATION policy."""

from __future__ import annotations

from magi.memory.evidence.models import AssertionScope, EvidenceClass, EvidenceClassification
from magi.memory.evidence.policy import resolve_l2_policy


def _classification(evidence_class: str) -> EvidenceClassification:
    return EvidenceClassification(
        evidence_class=evidence_class,
        reason_code="test",
        speaker_role=None,
        grounding_type=None,
        semantic_owner=None,
        originality_type=None,
        source_event_ids=[],
    )


def test_assertion_scope_has_interest_member():
    assert AssertionScope.INTEREST.label == "interest"


def test_external_observation_uses_interest_scope():
    decision = resolve_l2_policy(_classification(EvidenceClass.EXTERNAL_OBSERVATION.label))
    assert decision.assertion_scope == "interest"
