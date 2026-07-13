"""Phase 1 extraction prompt contract tests."""

from __future__ import annotations

from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT
from magi.memory.l2.phase1_models import L2Phase1FactClaim, L2TemporalCue


def test_phase1_prompt_requires_claim_objects_as_entities():
    assert "Every concrete object_ref used in fact_claims must also appear in entities" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_allows_external_observation_facts():
    assert "messages marked **[USER]** or **[EXTERNAL]**" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "For [EXTERNAL] messages, never use user:self" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_requires_exact_current_event_evidence():
    assert "exact quote copied from a current message" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Never cite Recent Context or History Context" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_fact_claim_exposes_grounded_temporal_cue_enum() -> None:
    claim = L2Phase1FactClaim.from_dict(
        {
            "fact_kind": "interaction_evidence",
            "temporal_cue": "recurring",
        }
    )

    assert claim.temporal_cue is L2TemporalCue.RECURRING
    assert claim.to_dict()["temporal_cue"] == "recurring"


def test_phase1_prompt_keeps_linguistic_cue_separate_from_lifecycle_policy() -> None:
    assert "interaction_evidence" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert '"temporal_cue": "one_off|recent|recurring|stable|unspecified"' in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "explicit wording only" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Do not use temporal_cue to choose retention" in PHASE1_EXTRACT_SYSTEM_PROMPT
