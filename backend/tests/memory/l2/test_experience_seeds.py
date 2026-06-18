"""Tests for L2 experience seed persistence."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_list_update_seed_and_attach_to_experience(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema

    seed_id = await store.create_experience_seed(
        seed_id="seed-japan-trip",
        seed_type="manual",
        status="candidate",
        title="Japan trip",
        description="User selected notes about planning and taking a Japan trip.",
        anchor_entity_ids=["place:japan", "travel:shinkansen"],
        anchor_topic_keys=["travel"],
        time_start=100.0,
        time_end=500.0,
        confidence=0.7,
        created_by="user",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[
            {
                "ref_type": "episode",
                "ref_id": "ep-train-ticket",
                "role": "trigger",
                "confidence": 0.9,
                "reason": "User selected this episode as the starting point.",
            },
            {
                "ref_type": "episode",
                "ref_id": "ep-google-map",
                "role": "support",
                "confidence": 0.65,
                "reason": "Nearby travel planning evidence.",
            },
        ],
    )
    duplicate_count = await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[
            {
                "ref_type": "episode",
                "ref_id": "ep-google-map",
                "role": "support",
                "confidence": 0.65,
            }
        ],
    )

    assert duplicate_count == 0
    seeds = await store.list_experience_seeds(status="candidate")
    assert [seed["seed_id"] for seed in seeds] == [seed_id]
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["seed_type"] == "manual"
    assert seed["title"] == "Japan trip"
    assert seed["anchor_entity_ids"] == ["place:japan", "travel:shinkansen"]
    assert seed["anchor_topic_keys"] == ["travel"]
    assert seed["confidence"] == 0.7
    assert seed["created_by"] == "user"

    evidence = await store.list_experience_seed_evidence(seed_id=seed_id)
    assert [(item["ref_type"], item["ref_id"], item["role"]) for item in evidence] == [
        ("episode", "ep-train-ticket", "trigger"),
        ("episode", "ep-google-map", "support"),
    ]

    updated = await store.update_experience_seed(seed_id=seed_id, status="accepted", confidence=0.82)
    assert updated is True
    updated_seed = await store.get_experience_seed(seed_id=seed_id)
    assert updated_seed is not None
    assert updated_seed["status"] == "accepted"
    assert updated_seed["confidence"] == 0.82

    await store.create_experience(
        experience_id="exp-japan-trip",
        source_seed_id=seed_id,
        status="active",
        title="Japan trip",
        time_start=100.0,
        time_end=500.0,
    )
    experience = await store.get_experience(experience_id="exp-japan-trip")
    assert experience is not None
    assert experience["source_seed_id"] == seed_id
