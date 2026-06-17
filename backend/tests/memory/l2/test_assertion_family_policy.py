from __future__ import annotations


def test_canonical_assertion_families_replace_taste_with_routine() -> None:
    from magi.memory.l2.assertion_family_policy import ASSERTION_FAMILY_POLICIES
    from magi.memory.l2.ontology import ASSERTION_FAMILY_ALLOWLIST

    assert "routine_profile" in ASSERTION_FAMILY_POLICIES
    assert "routine_profile" in ASSERTION_FAMILY_ALLOWLIST
    assert "taste_profile" not in ASSERTION_FAMILY_POLICIES
    assert "taste_profile" not in ASSERTION_FAMILY_ALLOWLIST


def test_family_policy_defines_lifecycle_and_snapshot_defaults() -> None:
    from magi.memory.l2.assertion_family_policy import get_assertion_family_policy

    mood = get_assertion_family_policy("mood")
    assert mood.default_temporal_scope == "session"
    assert mood.default_decay_policy == "session_decay"
    assert mood.default_ttl_seconds == 12 * 60 * 60
    assert mood.snapshot_bucket == "state"
    assert mood.value_i18n == "controlled"

    routine = get_assertion_family_policy("routine_profile")
    assert routine.default_temporal_scope == "stable"
    assert routine.default_decay_policy == "evidence_only"
    assert routine.default_ttl_seconds is None
    assert routine.snapshot_bucket == "core_traits"


def test_phase2_prompt_explains_assertion_family_semantics() -> None:
    from magi.memory.l2.pipeline.prompts import PHASE2_INTEGRATE_SYSTEM_PROMPT

    assert "## Assertion Family Semantics" in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert "`routine_profile`" in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert "`preference_profile`" in PHASE2_INTEGRATE_SYSTEM_PROMPT
    assert "`taste_profile`" not in PHASE2_INTEGRATE_SYSTEM_PROMPT
