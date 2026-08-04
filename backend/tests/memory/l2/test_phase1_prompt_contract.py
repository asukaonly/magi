"""Phase 1 extraction prompt contract tests."""

from __future__ import annotations

from magi.memory.l2.models import L2BatchEvent, L2EventWindow
from magi.memory.l2.pipeline.prompts import (
    PHASE1_EXTRACT_SYSTEM_PROMPT,
    render_phase1_extract_prompt,
)
from magi.memory.l2.phase1_models import (
    L2ClaimEvidenceMode,
    L2Phase1FactClaim,
    L2TemporalCue,
)


def test_phase1_prompt_requires_claim_objects_as_entities():
    assert "Every concrete object_ref used in fact_claims must also appear in entities" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_allows_external_observation_facts():
    assert "messages marked **[USER]** or **[EXTERNAL]**" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "For [EXTERNAL] messages, never use user:self" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_requires_exact_current_event_evidence():
    assert "exact quote copied from a current message" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "evidence_mode" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "antecedent_event_ids" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Recent Context is interpretation context, not standalone evidence" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )


def test_phase1_fact_claim_exposes_grounded_temporal_cue_enum() -> None:
    claim = L2Phase1FactClaim.from_dict(
        {
            "fact_kind": "interaction_evidence",
            "temporal_cue": "recurring",
        }
    )

    assert claim.temporal_cue is L2TemporalCue.RECURRING
    assert claim.to_dict()["temporal_cue"] == "recurring"


def test_phase1_fact_claim_exposes_context_evidence_contract() -> None:
    claim = L2Phase1FactClaim.from_dict(
        {
            "evidence_mode": "confirmation",
            "antecedent_event_ids": ["evt-assistant"],
        }
    )

    assert claim.evidence_mode is L2ClaimEvidenceMode.CONFIRMATION
    assert claim.antecedent_event_ids == ["evt-assistant"]
    assert claim.to_dict()["evidence_mode"] == "confirmation"


def test_phase1_prompt_keeps_linguistic_cue_separate_from_lifecycle_policy() -> None:
    assert "interaction_evidence" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert '"temporal_cue": "one_off|recent|recurring|stable|unspecified"' in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "explicit wording only" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Do not use temporal_cue to choose retention" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_forbids_translation_for_abstract_entity_types() -> None:
    assert "including activity, concept, topic, event" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "common nouns and phrases as well as proper nouns" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "slow morning walk and casual breakfast hunting" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "directional but unbound travel style" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "only when that exact alternate name appears in a current evidence message" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )


def test_phase1_render_separates_user_language_from_evidence_script() -> None:
    prompt = render_phase1_extract_prompt(
        event_window=L2EventWindow(
            events=[
                L2BatchEvent(
                    event_id="evt-1",
                    content="我最近在听 DIIV。",
                    author_type="user",
                )
            ]
        ),
        focal_subject={"entity_ref": "user:self", "entity_type": "user"},
        user_language="zh-CN",
        evidence_scripts=("Han", "Latin"),
    )

    assert "Configured user language: `zh-CN`" in prompt
    assert "not permission to translate evidence-derived fields" in prompt
    assert "Letter scripts detected in current evidence: Han, Latin" in prompt
    assert "Keep JSON keys, enum values, and protocol identifiers in English" in prompt
