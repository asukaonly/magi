"""Family routing, public metadata, snapshot placement and expiry contracts."""

from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trait,value,family,bucket,i18n,ttl",
    [
        ("preference.music", "Jazz", "preference_profile", "preferences", "literal", None),
        ("interest.diiv", "DIIV", "interest_profile", "preferences", "literal", None),
        ("project.magi", "Magi", "project_profile", "core_traits", "literal", None),
        (
            "routine.late_night_coding",
            "Night coding",
            "routine_profile",
            "core_traits",
            "literal",
            None,
        ),
        ("mood", "high", "mood", "state", "controlled", 43200),
        ("mood", "high", "mood", "state", "controlled", 123),
    ],
)
async def test_family_policy_controls_persisted_projection_and_expiry(
    l2_store_with_schema, monkeypatch, trait, value, family, bucket, i18n, ttl
):
    import magi.config
    from magi.config.models import AppConfig

    cfg = AppConfig()
    if ttl == 123:
        cfg.agent.memory.l2.assertion.mood_ttl_seconds = 123.0
    monkeypatch.setattr(magi.config, "get_config", lambda: cfg)
    now = 1700000000.0
    monkeypatch.setattr(time, "time", lambda: now)
    store = l2_store_with_schema
    assertion_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "user:policy",
            "entity_type": "user",
            "trait_name": trait,
            "trait_value": value,
            "confidence_score": 0.9,
            "volatility_index": 0.2,
            "validation_state": "stable",
            "evidence_events": ["event"],
            "source_domain": "user_authored",
            "inference_depth": "direct",
            "first_inferred_at": now,
            "last_validated_at": now,
        }
    )
    await store.apply_user_feedback(assertion_id=assertion_id, feedback="confirmed")
    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    assert assertion["trait_family"] == family
    assert assertion["trait_value_i18n"] == i18n
    assert assertion["assertion_family_snapshot_bucket"] == bucket
    assert assertion["expires_at"] == (now + ttl if ttl is not None else None)
    snapshot = await store.refresh_entity_snapshot(entity_id="user:policy", entity_type="user")
    assert snapshot is not None
    if trait == "mood":
        assert snapshot["current_mood"] == value
    elif trait.startswith("preference."):
        assert snapshot["preferences"]["music"] == value
        assert trait not in snapshot["core_traits"]
    elif trait.startswith("interest."):
        assert snapshot["preferences"][trait]["value"] == value
        assert snapshot["preferences"][trait]["family"] == family
    else:
        assert snapshot["core_traits"][trait] == value
        assert trait not in snapshot["preferences"]
    assert (await store.get_tom_snapshot(entity_id="user:policy", entity_type="user"))[
        "snapshot_id"
    ] == snapshot["snapshot_id"]
    if ttl is not None:
        monkeypatch.setattr(time, "time", lambda: now + ttl - 0.001)
        assert [
            row["assertion_id"]
            for row in await store.list_current_assertions(entity_id="user:policy")
        ] == [assertion_id]
        monkeypatch.setattr(time, "time", lambda: now + ttl)
        assert await store.list_current_assertions(entity_id="user:policy") == []
    else:
        monkeypatch.setattr(time, "time", lambda: now + 365 * 86400)
        assert [
            row["assertion_id"]
            for row in await store.list_current_assertions(entity_id="user:policy")
        ] == [assertion_id]
