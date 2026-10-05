import pytest
from magi.memory.l2.phase1_models import L2Phase1FactClaim, L2TemporalCue, L2ClaimEvidenceMode


@pytest.mark.parametrize(
    ("cue", "mode", "antecedents"),
    [
        ("recurring", "confirmation", ["evt-assistant"]),
        ("recent", "clarification", ["evt-prior-user", "evt-assistant"]),
        ("one_off", "direct", []),
        ("stable", "direct", []),
        ("unspecified", "direct", []),
    ],
)
def test_claim_wire_round_trip_preserves_temporal_and_context_evidence(cue, mode, antecedents):
    payload = {
        "claim_id": "claim-1",
        "subject_ref": "user:1",
        "predicate": "LIKES",
        "object_ref": "coffee",
        "object_type": "concept",
        "fact_kind": "interaction_evidence",
        "temporal_cue": cue,
        "evidence_mode": mode,
        "antecedent_event_ids": antecedents,
        "supporting_event_ids": ["evt-current"],
        "evidence_text": "I still like coffee.",
    }
    claim = L2Phase1FactClaim.from_dict(payload)
    assert claim.temporal_cue is L2TemporalCue(cue)
    assert claim.evidence_mode is L2ClaimEvidenceMode(mode)
    wire = claim.to_dict()
    assert {key: wire[key] for key in payload} == {**payload, "claim_id": ""}
    assert L2Phase1FactClaim.from_dict(wire) == claim
