"""Tests for assertion trait-family classification."""

from __future__ import annotations

import pytest

from magi.memory.l2.assertions.reconcile_state import L2ReconcileStateMixin


@pytest.mark.parametrize(
    ("trait_name", "expected_family"),
    [
        ("interest.diiv", "interest_profile"),
        ("project.magi", "project_profile"),
        ("routine.late_night_coding", "routine_profile"),
        ("preference.music", "preference_profile"),
    ],
)
def test_derive_trait_family_keeps_profile_semantics(
    trait_name: str,
    expected_family: str,
) -> None:
    state = L2ReconcileStateMixin()

    assert state._derive_trait_family(trait_name) == expected_family


def test_interest_traits_are_recommended_for_preference_snapshot() -> None:
    state = L2ReconcileStateMixin()

    assert (
        state._recommend_snapshot_field(
            trait_name="interest.diiv",
            status="stable",
        )
        == "preferences"
    )


@pytest.mark.parametrize(("catalog_name", "stored_summary", "value", "completeness", "expected"), [
    ("苹果", "", "like", "complete", "用户喜欢苹果。"),
    (None, "", "like", "partial", ""),
    ("苹果", "用户喜欢opaque-apple。", "like", "unavailable", ""),
    ("苹果", "用户不喜欢苹果。 原文时间: 上周", "dislike", "complete", "用户不喜欢苹果。 原文时间: 上周"),
])
async def test_reconcile_passes_complete_host_facts_to_l3_without_rewriting_assertion(
    l2_store_with_schema, catalog_name, stored_summary, value, completeness, expected,
):
    import time

    from magi.core.sqlite import sqlite_connection_async
    from magi.i18n import language_context
    from magi.memory.l3.models import StateChangePacket
    from magi.memory.l3.state_change_service import StateChangeService

    store = l2_store_with_schema
    now = time.time()
    if catalog_name:
        async with sqlite_connection_async(store.db_path) as db:
            await db.execute(
                "INSERT INTO entity_catalog (entity_id, canonical_name, entity_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("opaque-apple", catalog_name, "other", now, now),
            )
            await db.commit()
    assertion_id = await store.upsert_assertion_candidate({
        "entity_id": "user:local_user", "entity_type": "user",
        "trait_name": "preference.affinity", "trait_family": "preference_profile",
        "trait_value": value, "target_entity_id": "opaque-apple", "target_entity_type": "other",
        "natural_summary": stored_summary, "temporal_scope": "stable",
        "confidence_score": 0.9, "validation_state": "stable", "volatility_index": 0.2,
        "source_domain": "user_authored", "inference_depth": "direct",
        "evidence_events": ["event-a", "event-b"],
        "first_inferred_at": now - 72 * 3600, "last_validated_at": now,
    })
    with language_context("zh-CN"):
        [outcome] = await store.reconcile_entity(
            entity_id="user:local_user", entity_type="user",
            evidence_timestamps={"event-a": now - 72 * 3600, "event-b": now},
        )
        candidate = await StateChangeService().build_candidate(StateChangePacket(
            entity_id="user:local_user", entity_type="user", outcomes=[outcome],
        ))
    assert outcome.fact_completeness == completeness
    assert outcome.natural_summary == expected
    assert outcome.evidence_event_ids == ["event-a", "event-b"]
    assert outcome.winning_value == value
    assert outcome.time_span_hours == 72.0
    current = await store.get_tom_assertion(assertion_id=assertion_id)
    assert current is not None
    assert current["natural_summary"] == stored_summary
    if completeness == "complete":
        assert candidate is not None
        assert candidate.content == expected.rstrip("。.") + "。"
    else:
        assert candidate is None
