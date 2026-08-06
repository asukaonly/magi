"""Phase 1 extraction prompt contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

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


def test_phase1_prompt_requires_only_reusable_claim_objects_as_entities():
    assert "when it names a reusable catalog object" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Assertion-only literal values" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_keeps_complete_future_intent_as_goal_text() -> None:
    assert "complete `PLANS_TO` action text do not require an entity" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "keep the complete planned action in `object_ref`" in PHASE1_EXTRACT_SYSTEM_PROMPT


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
    assert "protocol rules and JSON schema are instructions, not evidence" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "never emit an entity surface or claim value copied from them" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "only when that exact alternate name appears in a current evidence message" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )


def test_phase1_prompt_does_not_embed_user_like_translation_examples() -> None:
    assert "慢悠悠的晨间散步和随性觅食" not in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "有方向但不设具体目的地的旅行方式" not in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "slow morning walk and casual breakfast hunting" not in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "directional but unbound travel style" not in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_reserves_other_for_unclassified_entities() -> None:
    assert "Prefer the most specific allowed entity type" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Use `group` for named bands, teams, communities, and collectives" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "Use `media` for named songs, albums, films, books, podcasts, and creative works" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "Use `concept` for abstract qualities, styles, and preferences" in (
        PHASE1_EXTRACT_SYSTEM_PROMPT
    )
    assert "Use `other` only when no other allowed type fits" in PHASE1_EXTRACT_SYSTEM_PROMPT


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


def test_phase1_render_uses_each_event_captured_timezone_with_offset() -> None:
    timestamp = datetime(2026, 7, 1, 1, 0, tzinfo=timezone.utc).timestamp()
    prompt = render_phase1_extract_prompt(
        event_window=L2EventWindow(
            events=[
                L2BatchEvent(
                    event_id="evt-history",
                    content="I started learning pottery.",
                    timestamp=timestamp,
                    author_type="user",
                    metadata_json={
                        "_temporal": {"calendar_timezone_id": "Asia/Shanghai"}
                    },
                )
            ]
        ),
        focal_subject={"entity_ref": "user:self", "entity_type": "user"},
    )

    assert "2026-07-01 09:00:00+08:00" in prompt
