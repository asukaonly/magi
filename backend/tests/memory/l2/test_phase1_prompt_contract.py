"""Phase 1 extraction prompt contract tests."""

from __future__ import annotations

from datetime import datetime, timezone

from magi.memory.l2.models import L2BatchEvent, L2EventWindow
from magi.memory.l2.ontology import ENTITY_TYPE_REGISTRY
from magi.memory.l2.pipeline.prompts import (
    PHASE1_EXTRACT_SYSTEM_PROMPT,
    render_phase1_extract_prompt,
)
from magi.memory.l2.phase1_models import (
    L2ClaimEvidenceMode,
    L2Phase1FactClaim,
    L2TemporalCue,
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


def test_phase1_prompt_defines_every_allowed_entity_type() -> None:
    for entity_type in ENTITY_TYPE_REGISTRY:
        assert f"- `{entity_type}` —" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "not a complete plan or action clause" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Do not emit complete sentences, long action clauses" in (
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
