"""Phase 1 extraction prompt contract tests."""

from __future__ import annotations

from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_requires_claim_objects_as_entities():
    assert "Every concrete object_ref used in fact_claims must also appear in entities" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_allows_external_observation_facts():
    assert "messages marked **[USER]** or **[EXTERNAL]**" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "For [EXTERNAL] messages, never use user:self" in PHASE1_EXTRACT_SYSTEM_PROMPT


def test_phase1_prompt_requires_exact_current_event_evidence():
    assert "exact quote copied from a current message" in PHASE1_EXTRACT_SYSTEM_PROMPT
    assert "Never cite Recent Context or History Context" in PHASE1_EXTRACT_SYSTEM_PROMPT
