from __future__ import annotations

import time

import pytest

from magi.memory.l2.corrections.models import CorrectionKind


async def _edge(
    store,  # type: ignore[no-untyped-def]
    *,
    object_id: str,
    event_id: str,
    observed_at: float | None = None,
    scope: dict | None = None,
) -> str:
    return await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id=object_id,
        object_type="place",
        evidence_event_ids=[event_id],
        confidence=0.8,
        observed_at=float(observed_at if observed_at is not None else time.time()),
        source_type="conversation",
        extraction_method="explicit",
        scope=scope,
    )


@pytest.mark.asyncio
async def test_reject_relationship_is_durable_across_replay(l2_store_with_schema):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:hangzhou", event_id="evt-original")

    rejected = await store.reject_edge(triple_id=triple_id)

    assert rejected is not None
    assert rejected["status"] == "user_rejected"
    corrections = await store.list_relationship_corrections(triple_id=triple_id)
    assert len(corrections) == 1
    assert corrections[0]["correction_kind"] == CorrectionKind.RECORD_ERROR
    history = await store.get_relationship_correction_history(triple_id=triple_id)
    assert [item["status"] for item in history["versions"]] == [
        "active",
        "user_rejected",
    ]

    for event_id in ("evt-replay-1", "evt-replay-2"):
        returned_id = await _edge(
            store,
            object_id="place:hangzhou",
            event_id=event_id,
        )
        assert returned_id == triple_id
    replayed = await store.get_relationship(triple_id=triple_id)
    assert replayed["status"] == "user_rejected"
    assert replayed["evidence_event_ids"] == ["evt-original"]
    assert await store.list_current_relationships(subject_id="user:u1") == []


@pytest.mark.asyncio
async def test_relationship_replacement_protects_authority_and_deduplicates_conflict(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    old_id = await _edge(store, object_id="place:hangzhou", event_id="evt-original")
    corrected = await store.apply_relationship_correction(
        triple_id=old_id,
        request_id="replace-city",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
    )

    assert corrected is not None
    current = corrected["current_relationship"]
    assert current["object_id"] == "place:shanghai"
    assert current["evidence_event_ids"] == []
    assert current["authority_ref"].startswith("correction:")
    old = await store.get_relationship(triple_id=old_id)
    assert old["status"] == "user_rejected"

    await _edge(store, object_id="place:hangzhou", event_id="evt-old-replay")
    first_conflict = await _edge(
        store,
        object_id="place:beijing",
        event_id="evt-conflict-1",
    )
    second_conflict = await _edge(
        store,
        object_id="place:beijing",
        event_id="evt-conflict-2",
    )
    assert second_conflict == first_conflict
    conflict = await store.get_relationship(triple_id=first_conflict)
    assert conflict["status"] == "conflicted"
    assert conflict["deprecated_by"] == current["triple_id"]
    assert conflict["evidence_event_ids"] == ["evt-conflict-1", "evt-conflict-2"]

    same_id = await _edge(
        store,
        object_id="place:shanghai",
        event_id="evt-support",
    )
    assert same_id == current["triple_id"]
    supported = await store.get_relationship(triple_id=same_id)
    assert supported["source_type"] == "user_correction"
    assert supported["authority_ref"].startswith("correction:")
    active = await store.list_current_relationships(subject_id="user:u1")
    assert [item["triple_id"] for item in active] == [current["triple_id"]]


@pytest.mark.asyncio
async def test_relationship_situation_change_keeps_pre_change_evidence_historical(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    effective_at = time.time() - 120
    old_id = await _edge(
        store,
        object_id="place:hangzhou",
        event_id="evt-original",
        observed_at=effective_at - 3600,
    )
    corrected = await store.apply_relationship_correction(
        triple_id=old_id,
        request_id="moved-city",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=effective_at,
    )
    current_id = corrected["current_relationship"]["triple_id"]

    returned_id = await _edge(
        store,
        object_id="place:hangzhou",
        event_id="evt-before-move",
        observed_at=effective_at - 60,
    )
    assert returned_id == old_id
    historical = await store.get_relationship(triple_id=old_id)
    assert historical["status"] == "deprecated"
    assert historical["valid_to"] == pytest.approx(effective_at)
    assert historical["last_observed_at"] <= effective_at
    assert historical["evidence_event_ids"] == ["evt-before-move", "evt-original"]
    active = await store.list_current_relationships(subject_id="user:u1")
    assert [item["triple_id"] for item in active] == [current_id]


@pytest.mark.asyncio
async def test_relationship_scope_refinement_and_revert(l2_store_with_schema):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:shanghai", event_id="evt-global")
    corrected = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="scope-city",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope={"project": "magi"},
    )

    assert corrected is not None
    scoped = corrected["current_relationship"]
    assert scoped["triple_id"] == triple_id
    assert scoped["scope"] == {"project": "magi"}
    assert await store.list_current_relationships(subject_id="user:u1") == []
    matching = await store.list_current_relationships(
        subject_id="user:u1",
        context_scope={"project": "magi"},
    )
    assert [item["triple_id"] for item in matching] == [triple_id]

    await _edge(store, object_id="place:shanghai", event_id="evt-wrong-scope")
    unchanged = await store.get_relationship(triple_id=triple_id)
    assert unchanged["scope"] == {"project": "magi"}
    assert unchanged["evidence_event_ids"] == []

    reverted = await store.revert_relationship_correction(
        correction_id=corrected["correction"]["correction_id"],
        request_id="revert-scope-city",
        actor_id="user:u1",
    )
    assert reverted["correction"]["state"] == "reverted"
    assert reverted["current_relationship"]["scope"] == {}
    assert reverted["current_relationship"]["evidence_event_ids"] == ["evt-global"]
    assert reverted["subject_revision"] == 2


@pytest.mark.asyncio
async def test_relationship_replacement_is_idempotent_and_revertible(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    old_id = await _edge(store, object_id="place:hangzhou", event_id="evt-original")
    command = {
        "triple_id": old_id,
        "request_id": "idempotent-city-replacement",
        "actor_id": "user:u1",
        "correction_kind": CorrectionKind.RECORD_ERROR,
        "replacement": {"object_id": "place:shanghai", "object_type": "place"},
    }

    first = await store.apply_relationship_correction(**command)
    second = await store.apply_relationship_correction(**command)

    assert first["created"] is True
    assert second["created"] is False
    assert first["correction"]["correction_id"] == second["correction"]["correction_id"]
    replacement_id = first["current_relationship"]["triple_id"]
    assert second["current_relationship"]["triple_id"] == replacement_id

    reverted = await store.revert_relationship_correction(
        correction_id=first["correction"]["correction_id"],
        request_id="revert-city-replacement",
        actor_id="user:u1",
    )

    assert reverted["current_relationship"]["triple_id"] == old_id
    assert reverted["current_relationship"]["status"] == "active"
    assert reverted["current_relationship"]["evidence_event_ids"] == ["evt-original"]
    replacement = await store.get_relationship(triple_id=replacement_id)
    assert replacement["status"] == "archived"
    history = await store.get_relationship_correction_history(triple_id=old_id)
    assert [item["status"] for item in history["versions"]] == [
        "active",
        "user_rejected",
        "active",
        "archived",
        "active",
    ]


@pytest.mark.asyncio
async def test_user_forgotten_relationship_does_not_warm_on_replay(l2_store_with_schema):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:hangzhou", event_id="evt-original")
    await store.forget_entity(entity_id="user:u1")

    replayed_id = await _edge(
        store,
        object_id="place:hangzhou",
        event_id="evt-replay",
    )

    assert replayed_id == triple_id
    replayed = await store.get_relationship(triple_id=triple_id)
    assert replayed["status"] == "archived"
    assert replayed["status_reason"] == "user_forget"
