from __future__ import annotations

import asyncio
import time

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.corrections.service import MemoryCorrectionValidationError
from magi.memory.l2.retrieval.common import bounded_scoped_candidate_limit
from magi.memory.l2.retrieval.relationship_history import (
    _build_historical_candidate_query,
)


async def _edge(
    store,  # type: ignore[no-untyped-def]
    *,
    object_id: str,
    event_id: str,
    predicate: str = "CURRENT_LIVES_IN",
    observed_at: float | None = None,
    scope: dict | None = None,
    expires_at: float | None = None,
    evidence_class: str | None = None,
) -> str:
    return await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate=predicate,
        object_id=object_id,
        object_type="place",
        evidence_event_ids=[event_id],
        confidence=0.8,
        observed_at=float(observed_at if observed_at is not None else time.time()),
        source_type="conversation",
        extraction_method="explicit",
        scope=scope,
        expires_at=expires_at,
        evidence_class=evidence_class,
    )


@pytest.mark.asyncio
async def test_relationship_history_follows_multi_step_nonexclusive_replacement_chain(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    original_id = await _edge(
        store,
        predicate="LIKES",
        object_id="place:hangzhou",
        event_id="evt-original",
    )
    first = await store.apply_relationship_correction(
        triple_id=original_id,
        request_id="replace-liked-place-first",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
    )
    assert first is not None
    middle_id = first["current_relationship"]["triple_id"]
    second = await store.apply_relationship_correction(
        triple_id=middle_id,
        request_id="replace-liked-place-second",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "place:beijing", "object_type": "place"},
    )
    assert second is not None
    current_id = second["current_relationship"]["triple_id"]

    history = await store.get_relationship_correction_history(triple_id=current_id)

    assert [item["request_id"] for item in history["corrections"]] == [
        "replace-liked-place-first",
        "replace-liked-place-second",
    ]
    assert [
        (item["object_id"], item["status"])
        for item in history["versions"]
    ] == [
        ("place:hangzhou", "active"),
        ("place:hangzhou", "user_rejected"),
        ("place:shanghai", "active"),
        ("place:shanghai", "user_rejected"),
        ("place:beijing", "active"),
    ]


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
    correction_at = float(corrections[0]["created_at"])
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
    historical = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=correction_at - 0.0001,
    )
    rejected_after = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=correction_at + 0.0001,
    )
    assert [item["triple_id"] for item in historical] == [triple_id]
    assert rejected_after == []


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
async def test_situation_change_rejects_time_before_relationship_started(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    observed_at = time.time() - 3600
    triple_id = await _edge(
        store,
        object_id="place:hangzhou",
        event_id="evt-original",
        observed_at=observed_at,
    )

    with pytest.raises(MemoryCorrectionValidationError, match="relationship start time"):
        await store.apply_relationship_correction(
            triple_id=triple_id,
            request_id="relationship-before-start",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SITUATION_CHANGED,
            replacement={"object_id": "place:shanghai", "object_type": "place"},
            effective_at=observed_at - 1,
        )


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
    correction_at = float(corrected["correction"]["created_at"])
    assert scoped["triple_id"] == triple_id
    assert scoped["scope"] == {"project": "magi"}
    assert await store.list_current_relationships(subject_id="user:u1") == []
    matching = await store.list_current_relationships(
        subject_id="user:u1",
        context_scope={"project": "magi"},
    )
    assert [item["triple_id"] for item in matching] == [triple_id]

    global_before = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=correction_at - 0.0001,
    )
    global_after = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=correction_at + 0.01,
    )
    scoped_after = await store.list_current_relationships(
        subject_id="user:u1",
        context_scope={"project": "magi", "activity": "coding"},
        effective_at=correction_at + 0.01,
    )
    assert [item["scope"] for item in global_before] == [{}]
    assert global_after == []
    assert [item["scope"] for item in scoped_after] == [{"project": "magi"}]

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

    reverted_at = float(reverted["correction"]["reverted_at"])
    between = await store.list_current_relationships(
        subject_id="user:u1",
        context_scope={"project": "magi"},
        effective_at=(correction_at + reverted_at) / 2,
    )
    after_revert = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=reverted_at + 0.01,
    )
    history = await store.list_current_relationships(
        subject_id="user:u1",
        context_scope={"project": "magi", "activity": "coding"},
        effective_range=(correction_at - 0.001, reverted_at + 0.01),
    )
    ordered_scopes = [
        item["scope"]
        for item in sorted(
            history,
            key=lambda item: item["_governed_range_segments"][0]["start"] or 0.0,
        )
    ]
    assert [item["scope"] for item in between] == [{"project": "magi"}]
    assert [item["scope"] for item in after_revert] == [{}]
    assert ordered_scopes == [{}, {"project": "magi"}, {}]
    assert len({item["_governed_version_id"] for item in history}) == 3


@pytest.mark.asyncio
async def test_relationship_scope_refinement_rejects_unsupported_fields(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:shanghai", event_id="evt-global")

    with pytest.raises(MemoryCorrectionValidationError, match="Unsupported scope fields"):
        await store.apply_relationship_correction(
            triple_id=triple_id,
            request_id="scope-city-unsupported",
            actor_id="user:u1",
            correction_kind=CorrectionKind.SCOPE_REFINEMENT,
            replacement={},
            scope={"unsupported": "value"},
        )


@pytest.mark.asyncio
async def test_relationship_history_uses_original_creation_when_first_version_has_no_start(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:shanghai", event_id="evt-global")
    original = await store.get_relationship(triple_id=triple_id)
    assert original is not None
    await asyncio.sleep(0.01)
    corrected = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="scope-city-without-version-start",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope={"project": "magi"},
    )
    assert corrected is not None
    correction_at = float(corrected["correction"]["created_at"])
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            UPDATE knowledge_graph_versions
            SET valid_from = NULL
            WHERE triple_id = ? AND previous_version_id IS NULL
            """,
            (triple_id,),
        )
        await db.commit()

    historical = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=(float(original["created_at"]) + correction_at) / 2,
    )

    assert [item["triple_id"] for item in historical] == [triple_id]
    assert [item["scope"] for item in historical] == [{}]


@pytest.mark.asyncio
async def test_relationship_history_does_not_borrow_mutable_current_metadata(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:shanghai", event_id="evt-global")
    original = await store.get_relationship(triple_id=triple_id)
    assert original is not None
    await asyncio.sleep(0.01)
    corrected = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="scope-city-mutable-metadata",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope={"project": "magi"},
    )
    assert corrected is not None
    correction_at = float(corrected["correction"]["created_at"])
    await asyncio.sleep(0.01)
    mutation_at = time.time()
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            UPDATE knowledge_graph
            SET evidence_class = 'external_sensor', expires_at = ?,
                source_type = 'mutated_current', natural_summary = 'mutated current',
                updated_at = ?
            WHERE triple_id = ?
            """,
            (float(original["created_at"]) - 1, mutation_at, triple_id),
        )
        await db.commit()

    historical = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=(float(original["created_at"]) + correction_at) / 2,
    )
    scoped_before_mutation = await store.list_current_relationships(
        subject_id="user:u1",
        context_scope={"project": "magi"},
        evidence_classes=["user_self_report"],
        effective_at=(correction_at + mutation_at) / 2,
    )

    assert [item["triple_id"] for item in historical] == [triple_id]
    assert historical[0]["evidence_class"] is None
    assert historical[0]["expires_at"] is None
    assert historical[0]["source_type"] == original["source_type"]
    assert historical[0]["natural_summary"] == original["natural_summary"]
    assert [item["triple_id"] for item in scoped_before_mutation] == [triple_id]
    assert scoped_before_mutation[0]["evidence_class"] == "user_self_report"
    assert scoped_before_mutation[0]["expires_at"] is None
    assert scoped_before_mutation[0]["source_type"] == "user_correction"


@pytest.mark.asyncio
async def test_relationship_history_keeps_versioned_evidence_class_filtering(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _edge(
        store,
        object_id="place:shanghai",
        event_id="evt-observed",
        evidence_class="observed_activity",
    )
    corrected = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="scope-city-evidence-class",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope={"project": "magi"},
    )
    assert corrected is not None
    correction_at = float(corrected["correction"]["created_at"])
    reverted = await store.revert_relationship_correction(
        correction_id=corrected["correction"]["correction_id"],
        request_id="revert-scope-city-evidence-class",
        actor_id="user:u1",
    )
    assert reverted is not None
    reverted_at = float(reverted["correction"]["reverted_at"])
    scoped_at = (correction_at + reverted_at) / 2

    wrong_class = await store.list_current_relationships(
        context_scope={"project": "magi"},
        evidence_classes=["calendar_commitment"],
        effective_at=scoped_at,
    )
    matching_class = await store.list_current_relationships(
        context_scope={"project": "magi"},
        evidence_classes=["user_self_report"],
        effective_at=scoped_at,
    )

    assert wrong_class == []
    assert [item["triple_id"] for item in matching_class] == [triple_id]
    assert matching_class[0]["evidence_class"] == "user_self_report"


@pytest.mark.asyncio
async def test_relationship_evidence_filter_excludes_unknown_current_and_history(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _edge(
        store,
        object_id="place:unknown-evidence",
        event_id="evt-unknown-evidence",
    )
    original = await store.get_relationship(triple_id=triple_id)
    assert original is not None

    current = await store.list_current_relationships(
        subject_id="user:u1",
        evidence_classes=["user_self_report"],
    )
    assert current == []

    corrected = await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="scope-unknown-evidence",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope={"project": "magi"},
    )
    assert corrected is not None
    correction_at = float(corrected["correction"]["created_at"])
    historical_at = (float(original["created_at"]) + correction_at) / 2

    filtered_history = await store.list_current_relationships(
        subject_id="user:u1",
        evidence_classes=["user_self_report"],
        effective_at=historical_at,
    )
    unfiltered_history = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=historical_at,
    )

    assert filtered_history == []
    assert [item["triple_id"] for item in unfiltered_history] == [triple_id]


@pytest.mark.asyncio
async def test_relationship_history_keeps_versioned_expiration(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    old_id = await _edge(
        store,
        object_id="place:hangzhou",
        event_id="evt-expiring",
        observed_at=now - 100,
        expires_at=now + 10,
    )
    corrected = await store.apply_relationship_correction(
        triple_id=old_id,
        request_id="future-city-after-expiration",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        effective_at=now + 100,
    )
    assert corrected is not None

    before_expiration = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=now + 5,
    )
    after_expiration = await store.list_current_relationships(
        subject_id="user:u1",
        effective_at=now + 20,
    )

    assert [item["triple_id"] for item in before_expiration] == [old_id]
    assert before_expiration[0]["expires_at"] == pytest.approx(now + 10)
    assert after_expiration == []


@pytest.mark.asyncio
async def test_relationship_history_candidate_window_filters_future_noise_before_limit(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    as_of = time.time()
    target_id = await _edge(
        store,
        object_id="place:historical-target",
        event_id="evt-historical-target",
        observed_at=as_of - 100,
    )
    future_rows = [
        (
            f"triple-future-{index}",
            "user:u1",
            "user",
            "CURRENT_LIVES_IN",
            f"place:future-{index}",
            "place",
            "explicit_fact",
            0.8,
            f'["evt-future-{index}"]',
            as_of + 1_000 + index,
            as_of + 1_000 + index,
            "conversation",
            "explicit",
            as_of + 1_000 + index,
            "active",
            as_of + index,
            as_of + index,
            f"slot-future-{index}",
            f"claim-future-{index}",
            "global",
            "{}",
        )
        for index in range(620)
    ]
    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                fact_kind, confidence, evidence_event_ids, first_observed_at,
                last_observed_at, source_type, extraction_method, valid_from, status,
                created_at, updated_at, slot_key, claim_fingerprint, scope_key,
                scope_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            future_rows,
        )
        await db.commit()

    historical = await store.list_current_relationships(
        predicates=["CURRENT_LIVES_IN"],
        effective_at=as_of,
        limit=1,
    )

    assert [item["triple_id"] for item in historical] == [target_id]


@pytest.mark.asyncio
async def test_relationship_history_candidate_window_ignores_closed_chain_pressure(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    query_at = time.time() + 1_000
    observed_at = query_at - 2_000
    target_id = await _edge(
        store,
        object_id="place:active-target",
        event_id="evt-active-target",
        observed_at=observed_at,
    )
    closed_rows = []
    active_versions = []
    for index in range(620):
        triple_id = f"triple-closed-{index}"
        slot_key = f"slot-closed-{index}"
        claim_fingerprint = f"claim-closed-{index}"
        closed_at = query_at - 10 + index * 0.001
        closed_rows.append(
            (
                triple_id,
                "user:u1",
                "user",
                "CURRENT_LIVES_IN",
                f"place:closed-{index}",
                "place",
                "explicit_fact",
                0.8,
                f'["evt-closed-{index}"]',
                observed_at,
                observed_at,
                "conversation",
                "explicit",
                observed_at,
                "user_rejected",
                observed_at,
                closed_at,
                slot_key,
                claim_fingerprint,
                "global",
                "{}",
            )
        )
        active_versions.append(
            (
                f"version-closed-{index}",
                triple_id,
                slot_key,
                claim_fingerprint,
                "user:u1",
                "user",
                "CURRENT_LIVES_IN",
                f"place:closed-{index}",
                "place",
                "explicit_fact",
                0.8,
                f'["evt-closed-{index}"]',
                "",
                "active",
                observed_at,
                "global",
                "{}",
                closed_at - 0.000001,
                "",
                1,
                observed_at,
                observed_at,
                "conversation",
                "explicit",
                "user_self_report",
                observed_at,
            )
        )

    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                fact_kind, confidence, evidence_event_ids, first_observed_at,
                last_observed_at, source_type, extraction_method, valid_from, status,
                created_at, updated_at, slot_key, claim_fingerprint, scope_key,
                scope_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            closed_rows,
        )
        await db.executemany(
            """
            INSERT INTO knowledge_graph_versions(
                version_id, triple_id, slot_key, claim_fingerprint, subject_id,
                subject_type, predicate, object_id, object_type, fact_kind,
                confidence, evidence_event_ids, evidence_text, status, valid_from,
                scope_key, scope_json, created_at, natural_summary,
                observation_count, first_observed_at, last_observed_at, source_type,
                extraction_method, evidence_class, edge_created_at,
                governance_complete
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, 1
            )
            """,
            active_versions,
        )
        await db.commit()

    assert bounded_scoped_candidate_limit(64) == 512
    historical = await store.list_current_relationships(
        subject_id="user:u1",
        predicates=["CURRENT_LIVES_IN"],
        effective_at=query_at,
        limit=64,
    )

    assert [item["triple_id"] for item in historical] == [target_id]


@pytest.mark.asyncio
async def test_relationship_history_common_query_uses_governed_version_index(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    triple_id = await _edge(store, object_id="place:shanghai", event_id="evt-index")
    await store.apply_relationship_correction(
        triple_id=triple_id,
        request_id="scope-city-index-plan",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SCOPE_REFINEMENT,
        replacement={},
        scope={"project": "magi"},
    )
    candidate_sql, args = _build_historical_candidate_query(
        subject_id="user:u1",
        entity_ids=None,
        direction="outgoing",
        object_id=None,
        predicates=["CURRENT_LIVES_IN"],
        object_types=None,
        evidence_classes=None,
        triple_ids=None,
        requested_scope={"project": "magi"},
        effective_at=time.time(),
        effective_range=None,
        limit=10,
    )

    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            f"EXPLAIN QUERY PLAN {candidate_sql}",
            tuple(args),
        ) as cursor:
            plan_rows = await cursor.fetchall()

    plan_details = [str(row[3]) for row in plan_rows]
    assert any(
        "idx_kg_versions_governed_subject_time" in detail
        and "SEARCH v" in detail
        for detail in plan_details
    ), plan_details
    assert not any(
        detail.startswith("SCAN v") or detail.startswith("SCAN g")
        for detail in plan_details
    ), plan_details


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
