from __future__ import annotations

import time
import warnings

import aiosqlite
import pytest

from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.corrections.service import MemoryCorrectionConflictError
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.maintenance import L2EntityMaintenance
from magi.memory.l2.models import L2ProjectionLease
from magi.memory.l3.models import L3Candidate


def _projection_lease(row: dict[str, object]) -> L2ProjectionLease:
    return L2ProjectionLease(
        event_id=str(row["event_id"]),
        lease_token=str(row["lease_token"]),
        attempt_count=int(row["attempt_count"]),
    )


async def _insert_projection_block(
    store,  # type: ignore[no-untyped-def]
    *,
    event_id: str,
    target_id: str,
) -> None:
    selector_kind = "time_range" if target_id.startswith("time:") else "episode"
    operation_id = f"forget:{target_id}:{event_id}"
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, ?, ?, '{}', 'test_projection_block', ?, ?)
            """,
            (operation_id, selector_kind, operation_id, time.time(), time.time()),
        )
        await db.execute(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('episode_formation', ?, ?, ?, ?)
            """,
            (target_id, event_id, operation_id, time.time()),
        )
        await db.commit()


async def _insert_entity_projection_candidate(
    store,  # type: ignore[no-untyped-def]
    *,
    event_id: str,
    entity_id: str,
) -> None:
    operation_id = f"forget-entity-candidate:{entity_id}:{event_id}"
    now = time.time()
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, 'entity', ?, '{}', 'test_entity_candidate', ?, ?)
            """,
            (operation_id, operation_id, now, now),
        )
        await db.execute(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('entity_projection_candidate', ?, ?, ?, ?)
            """,
            (entity_id, event_id, operation_id, now),
        )
        await db.commit()


async def _assertion(store, *, value: str, event_ids: list[str]) -> str:  # type: ignore[no-untyped-def]
    now = time.time() - 60
    return await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "favorite_city",
            "trait_value": value,
            "confidence_score": 0.8,
            "evidence_events": event_ids,
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )


async def _edge(store, *, object_id: str, event_ids: list[str]) -> str:  # type: ignore[no-untyped-def]
    return await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id=object_id,
        object_type="place",
        evidence_event_ids=event_ids,
        confidence=0.8,
        observed_at=time.time() - 60,
        source_type="conversation",
        extraction_method="explicit",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "writer_kind",
    ["assertion", "edge", "catalog", "facet", "episode"],
)
async def test_entity_candidate_promotes_only_after_target_lineage_write(
    l2_store_with_schema,
    writer_kind: str,
) -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    store = l2_store_with_schema
    event_id = f"evt-entity-candidate-{writer_kind}"
    entity_id = "person:private" if writer_kind in {"catalog", "facet"} else "user:u1"
    await _insert_entity_projection_candidate(
        store,
        event_id=event_id,
        entity_id=entity_id,
    )

    if writer_kind == "assertion":
        assertion_id = await _assertion(
            store,
            value="Blocked candidate",
            event_ids=[event_id],
        )
        assert assertion_id.startswith("blocked:")
        assert await store.list_current_assertions(entity_id=entity_id) == []
    elif writer_kind == "edge":
        edge_id = await _edge(
            store,
            object_id="place:blocked-candidate",
            event_ids=[event_id],
        )
        assert await store.get_relationship(triple_id=edge_id) is None
    elif writer_kind == "catalog":
        catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
        await catalog.initialize()
        await catalog.upsert_entity(
            canonical_name="Candidate User",
            entity_type="person",
            entity_id=entity_id,
            source_event_ids=[event_id],
        )
        assert await catalog.list_entities(limit=10, entity_ids=[entity_id]) == []
    elif writer_kind == "facet":
        await store.upsert_entity_facet(
            entity_id=entity_id,
            entity_type="person",
            facet_name="role",
            facet_value="blocked-candidate",
            evidence_event_ids=[event_id],
            confidence=0.8,
            observed_at=time.time(),
            source_type="conversation",
        )
        assert await store.list_entity_facets(entity_id=entity_id) == []
    else:
        await store.create_episode(
            episode_id="episode-blocked-candidate",
            status="active",
            time_start=1.0,
            time_end=2.0,
            primary_entity_ids=[entity_id],
        )
        assert (
            await store.add_episode_events(
                episode_id="episode-blocked-candidate",
                event_ids=[event_id],
            )
            == 0
        )

    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            """
            SELECT block_kind
            FROM memory_projection_blocks
            WHERE target_id = ? AND event_id = ?
            ORDER BY block_kind
            """,
            (entity_id, event_id),
        ) as cursor:
            assert await cursor.fetchall() == [
                ("entity_projection",),
                ("entity_projection_candidate",),
            ]


@pytest.mark.asyncio
async def test_source_event_forget_removes_only_target_support(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    assertion_id = await _assertion(
        store,
        value="Hangzhou",
        event_ids=["evt-remove", "evt-keep"],
    )
    edge_id = await _edge(
        store,
        object_id="place:hangzhou",
        event_ids=["evt-remove", "evt-keep"],
    )
    assertion_before = await store.get_tom_assertion(assertion_id=assertion_id)
    edge_before = await store.get_relationship(triple_id=edge_id)

    result = await store.forget_source_events(
        ["evt-remove"],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    edge = await store.get_relationship(triple_id=edge_id)
    assert assertion is not None and assertion_before is not None
    assert assertion["status"] != "archived"
    assert assertion["evidence_events"] == ["evt-keep"]
    assert assertion["confidence_score"] < assertion_before["confidence_score"]
    assert edge is not None and edge_before is not None
    assert edge["status"] == "active"
    assert edge["evidence_event_ids"] == ["evt-keep"]
    assert edge["observation_count"] == 1
    assert edge["confidence"] < edge_before["confidence"]
    assert edge["evidence_text"] == ""
    assert edge["natural_summary"] == ""
    assert result["source_event_tombstones"] == 1

    repeated = await store.forget_source_events(
        ["evt-remove"],
        reason="user_delete_event",
    )
    assert repeated["source_event_tombstones"] == 0
    assert (await store.get_tom_assertion(assertion_id=assertion_id))["evidence_events"] == [
        "evt-keep"
    ]
    assert (await store.get_relationship(triple_id=edge_id))["evidence_event_ids"] == ["evt-keep"]


@pytest.mark.asyncio
async def test_source_event_forget_archives_claims_with_no_remaining_support(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _assertion(store, value="Tokyo", event_ids=["evt-only"])
    edge_id = await _edge(store, object_id="place:tokyo", event_ids=["evt-only"])

    await store.forget_source_events(["evt-only"], reason="user_delete_event")

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    edge = await store.get_relationship(triple_id=edge_id)
    assert assertion is not None
    assert assertion["status"] == "archived"
    assert assertion["authority_ref"] == "forget:event"
    assert assertion["evidence_events"] == []
    assert edge is not None
    assert edge["status"] == "archived"
    assert edge["status_reason"] == "user_forget"
    assert edge["authority_ref"] == "forget:event"
    assert edge["evidence_event_ids"] == []
    assert await store.list_current_assertions(entity_id="user:u1") == []
    assert await store.list_current_relationships(subject_id="user:u1") == []
    assert (
        await store.list_tom_assertions(
            include_inactive=True,
            query="Tokyo",
        )
        == []
    )
    assert (
        await store.count_tom_assertions(
            include_inactive=True,
            query="Tokyo",
        )
        == 0
    )
    assert await store.batch_list_tom_assertions(
        entity_ids=["user:u1"],
        include_inactive=True,
    ) == {"user:u1": []}
    assert (
        await store.get_relationships(
            include_inactive=True,
            query="place:tokyo",
        )
        == []
    )
    assert (
        await store.count_relationships(
            include_inactive=True,
            query="place:tokyo",
        )
        == 0
    )
    assert await store.batch_get_relationships(
        entity_ids=["user:u1"],
        status_filters=["archived"],
    ) == {"user:u1": []}


@pytest.mark.asyncio
async def test_source_event_tombstone_blocks_first_future_claims(l2_store_with_schema) -> None:
    store = l2_store_with_schema

    result = await store.forget_source_events(
        ["evt-not-yet-extracted"],
        reason="user_delete_event",
    )
    assertion_id = await _assertion(
        store,
        value="Osaka",
        event_ids=["evt-not-yet-extracted"],
    )
    edge_id = await _edge(
        store,
        object_id="place:osaka",
        event_ids=["evt-not-yet-extracted"],
    )

    assert result["source_event_tombstones"] == 1
    assert await store.get_tom_assertion(assertion_id=assertion_id) is None
    assert await store.get_relationship(triple_id=edge_id) is None
    assert await store.active_correction_evidence_event_ids(
        ["evt-not-yet-extracted", "evt-unrelated"]
    ) == {"evt-not-yet-extracted"}


@pytest.mark.asyncio
async def test_time_range_event_block_rejects_new_claims_without_blocking_episode_sources(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    async with aiosqlite.connect(store.db_path) as db:
        await db.executemany(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, ?, ?, '{}', 'test', 1, 1)
            """,
            [
                ("operation-time-claims", "time_range", "hash-time-claims"),
                ("operation-episode-claims", "episode", "hash-episode-claims"),
            ],
        )
        await db.executemany(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('episode_formation', ?, ?, ?, 1)
            """,
            [
                (
                    "time:hash-time-claims",
                    "evt-time-range-claims",
                    "operation-time-claims",
                ),
                (
                    "episode:ordinary",
                    "evt-episode-only-claims",
                    "operation-episode-claims",
                ),
            ],
        )
        await db.commit()

    blocked_assertion_id = await _assertion(
        store,
        value="Blocked City",
        event_ids=["evt-time-range-claims"],
    )
    blocked_edge_id = await _edge(
        store,
        object_id="place:blocked-city",
        event_ids=["evt-time-range-claims"],
    )
    allowed_assertion_id = await _assertion(
        store,
        value="Allowed City",
        event_ids=["evt-episode-only-claims"],
    )
    allowed_edge_id = await _edge(
        store,
        object_id="place:allowed-city",
        event_ids=["evt-episode-only-claims"],
    )

    assert await store.get_tom_assertion(assertion_id=blocked_assertion_id) is None
    assert await store.get_relationship(triple_id=blocked_edge_id) is None
    assert await store.get_tom_assertion(assertion_id=allowed_assertion_id) is not None
    assert await store.get_relationship(triple_id=allowed_edge_id) is not None


@pytest.mark.asyncio
async def test_clear_removes_source_event_tombstones(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    await store.forget_source_events(["evt-clear-tombstone"], reason="user_delete_event")

    await store.clear()

    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM memory_source_event_tombstones") as cursor:
            assert await cursor.fetchone() == (0,)
    assertion_id = await _assertion(
        store,
        value="Kyoto",
        event_ids=["evt-clear-tombstone"],
    )
    assert await store.get_tom_assertion(assertion_id=assertion_id) is not None


@pytest.mark.asyncio
async def test_source_event_forget_invalidates_explicit_derivations_and_keeps_user_fields(
    l2_store_with_schema,
) -> None:
    from magi.memory.l3.summary_store import L3SummaryStore

    store = l2_store_with_schema
    now = time.time()
    await store.create_episode(
        episode_id="episode-source",
        status="active",
        time_start=now - 100,
        time_end=now,
        label="Generated episode label",
        summary="Generated episode summary",
        source_event_count=2,
    )
    await store.update_episode(
        episode_id="episode-source",
        user_label="My episode",
        user_note="Keep this note",
        user_pinned=True,
    )
    await store.add_episode_events(
        episode_id="episode-source",
        event_ids=["evt-remove", "evt-keep"],
    )
    await store.create_experience(
        experience_id="experience-source",
        status="active",
        title="Generated experience title",
        time_start=now - 100,
        time_end=now,
        intent="Generated intent",
        user_label="My experience",
        user_note="Keep experience note",
        user_cover_asset_ref="asset:user-cover",
        user_pinned=True,
        source_episode_count=1,
        source_event_count=2,
    )
    await store.add_experience_members(
        experience_id="experience-source",
        members=[
            {"member_type": "episode", "member_id": "episode-source"},
            {"member_type": "event", "member_id": "evt-remove"},
        ],
    )
    await store.replace_experience_chapters(
        experience_id="experience-source",
        chapters=[
            {
                "chapter_id": "chapter-source",
                "title": "Generated chapter",
                "summary": "Generated chapter summary",
                "episode_ids": ["episode-source"],
                "event_ids": ["evt-remove", "evt-keep"],
            }
        ],
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO experience_key_events(
                experience_id, event_id, role, reason, confidence, added_at
            ) VALUES ('experience-source', 'evt-remove', 'turning_point',
                      'generated reason', 0.9, ?)
            """,
            (now,),
        )
        await db.commit()

    l3 = L3SummaryStore(db_path=store.db_path, vector_enabled=False)
    await l3.initialize()
    summary = await l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content="Generated summary",
            source_event_ids=["evt-remove"],
            insight_key="summary-source",
        )
    )
    await store.create_experience_seed(
        seed_id="seed-system",
        seed_type="project",
        status="candidate",
        title="Generated seed",
        description="Generated seed description",
        created_by="system",
        source_ref_type="summary",
        source_ref_id=summary["summary_id"],
    )
    await store.add_experience_seed_evidence(
        seed_id="seed-system",
        evidence=[{"ref_type": "summary", "ref_id": summary["summary_id"]}],
    )
    await store.create_experience_seed(
        seed_id="seed-user",
        seed_type="manual",
        status="accepted",
        title="My seed title",
        description="Generated from episode",
        created_by="user",
        source_ref_type="episode",
        source_ref_id="episode-source",
    )
    await store.add_experience_seed_evidence(
        seed_id="seed-user",
        evidence=[{"ref_type": "episode", "ref_id": "episode-source"}],
    )

    result = await store.forget_source_events(["evt-remove"], reason="user_delete_event")

    episode = await store.get_episode(episode_id="episode-source")
    assert episode is not None
    assert episode["status"] == "invalidated"
    assert episode["source_event_count"] == 1
    assert episode["user_label"] == "My episode"
    assert episode["user_note"] == "Keep this note"
    assert episode["user_pinned"] is True
    assert episode["summary"] == "Generated episode summary"
    assert [
        row["event_id"] for row in await store.list_episode_events(episode_id="episode-source")
    ] == ["evt-keep"]

    experience = await store.get_experience(experience_id="experience-source")
    assert experience is not None
    assert experience["status"] == "invalidated"
    assert experience["user_label"] == "My experience"
    assert experience["user_note"] == "Keep experience note"
    assert experience["user_cover_asset_ref"] == "asset:user-cover"
    assert experience["user_pinned"] is True
    assert experience["title"] == "Generated experience title"
    assert await store.list_experience_members(experience_id="experience-source") == []
    assert experience["chapters"][0]["episode_ids"] == []
    assert experience["chapters"][0]["event_ids"] == ["evt-keep"]

    system_seed = await store.get_experience_seed(seed_id="seed-system")
    user_seed = await store.get_experience_seed(seed_id="seed-user")
    assert system_seed is not None and user_seed is not None
    assert system_seed["status"] == "stale"
    assert system_seed["title"] is None
    assert system_seed["description"] is None
    assert system_seed["source_ref_id"] is None
    assert user_seed["status"] == "stale"
    assert user_seed["title"] == "My seed title"
    assert user_seed["description"] is None
    assert user_seed["source_ref_id"] is None
    assert await store.list_experience_seed_evidence(seed_id="seed-system") == []
    assert await store.list_experience_seed_evidence(seed_id="seed-user") == []
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            "SELECT derivation_state FROM summaries WHERE summary_id = ?",
            (summary["summary_id"],),
        ) as cursor:
            assert await cursor.fetchone() == ("retired",)
    assert result["episodes"] == 1
    assert result["experiences"] == 1
    assert result["experience_seeds"] == 2


@pytest.mark.asyncio
async def test_tombstone_completes_queued_projection_before_stale_batch_runs(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assert await store.enqueue_projection_job(
        event_id="evt-queued-forgotten",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(consumer_name="test-worker", limit=1)
    assert [row["event_id"] for row in claimed] == ["evt-queued-forgotten"]
    assert (
        await store.bind_projection_job_batch(
            [_projection_lease(claimed[0])],
            consumer_name="test-worker",
        )
        == 1
    )

    await store.tombstone_source_events(
        ["evt-queued-forgotten"],
        reason="user_delete_event",
    )

    assert (
        await store.mark_projection_jobs_running(
            [_projection_lease(claimed[0])],
            consumer_name="test-worker",
        )
        == 0
    )
    assert not await store.enqueue_projection_job(
        event_id="evt-queued-forgotten",
        source="chat",
        event_type="UserMessage",
    )
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("""
            SELECT status, last_error FROM l2_projection_jobs
            WHERE event_id = 'evt-queued-forgotten'
            """) as cursor:
            assert await cursor.fetchone() == ("completed", "source_event_forgotten")
        async with db.execute("""
            SELECT COUNT(*) FROM episode_events
            WHERE event_id = 'evt-queued-forgotten'
            """) as cursor:
            assert await cursor.fetchone() == (0,)


@pytest.mark.asyncio
async def test_projection_claim_skips_a_pending_job_with_a_global_tombstone(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assert await store.enqueue_projection_job(
        event_id="evt-pending-forgotten",
        source="chat",
        event_type="UserMessage",
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('evt-pending-forgotten', 'user_delete_event', ?)
            """,
            (time.time(),),
        )
        await db.commit()

    assert await store.claim_projection_jobs(consumer_name="test-worker", limit=1) == []
    assert await store.claim_ready_projection_jobs(consumer_name="test-worker", limit=1) == []


@pytest.mark.asyncio
async def test_projection_batch_start_is_all_or_nothing_after_one_event_is_forgotten(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    for event_id in ("evt-batch-active", "evt-batch-forgotten"):
        assert await store.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    claimed = await store.claim_projection_jobs(consumer_name="test-worker", limit=2)
    assert {row["event_id"] for row in claimed} == {
        "evt-batch-active",
        "evt-batch-forgotten",
    }
    projection_leases = [_projection_lease(row) for row in claimed]
    assert (
        await store.bind_projection_job_batch(
            projection_leases,
            consumer_name="test-worker",
        )
        == 2
    )

    await store.tombstone_source_events(
        ["evt-batch-forgotten"],
        reason="user_delete_event",
    )

    assert (
        await store.mark_projection_jobs_running(
            projection_leases,
            consumer_name="test-worker",
        )
        == 0
    )
    reclaimed = await store.claim_projection_jobs(consumer_name="test-worker", limit=2)
    assert [row["event_id"] for row in reclaimed] == ["evt-batch-active"]
    async with aiosqlite.connect(store.db_path) as db:
        rows = await (await db.execute("""
                SELECT event_id, status FROM l2_projection_jobs
                WHERE event_id IN ('evt-batch-active', 'evt-batch-forgotten')
                ORDER BY event_id
                """)).fetchall()
    assert rows == [
        ("evt-batch-active", "queued"),
        ("evt-batch-forgotten", "completed"),
    ]


@pytest.mark.asyncio
async def test_source_event_forget_removes_public_entity_evidence(
    l2_store_with_schema,
) -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.initialize()
    await catalog.upsert_entity(
        canonical_name="Retained person",
        entity_type="person",
        entity_id="person:two",
        source_event_ids=["evt-remove"],
    )
    await catalog.add_alias(
        entity_id="person:two",
        alias_text="Private mixed mention",
        source_event_ids=["evt-remove", "evt-keep"],
    )
    await catalog.add_alias(
        entity_id="person:two",
        alias_text="Stale private alias",
        source_event_ids=["evt-remove"],
    )
    await catalog.add_alias(entity_id="person:two", alias_text="Independent label")
    await catalog.upsert_entity(
        canonical_name="Public retained alias",
        entity_type="person",
        entity_id="person:two",
        source_event_ids=["evt-keep"],
    )
    await catalog.add_alias(
        entity_id="person:two",
        alias_text="Public retained alias",
        source_event_ids=["evt-keep"],
    )
    await catalog.upsert_entity(
        canonical_name="Private Sole Canonical",
        entity_type="person",
        entity_id="person:private",
        source_event_ids=["evt-remove"],
    )
    await catalog.add_alias(
        entity_id="person:private",
        alias_text="Private sole mention",
        source_event_ids=["evt-remove"],
    )
    await catalog.upsert_entity(
        canonical_name="Independent person",
        entity_type="person",
        entity_id="person:independent",
    )
    await catalog.add_alias(
        entity_id="person:independent",
        alias_text="Independent nickname",
    )
    await catalog.record_mention(
        mention_text="Private sole mention",
        normalized_surface="private sole mention",
        entity_type="person",
        evidence_event_ids=["evt-remove"],
        evidence_text="Private sole evidence text",
        resolved_entity_id="person:private",
        confidence=0.8,
    )
    await catalog.record_mention(
        mention_text="Private mixed mention",
        normalized_surface="private mixed mention",
        entity_type="person",
        evidence_event_ids=["evt-remove", "evt-keep"],
        evidence_text="Private mixed evidence text",
        resolved_entity_id="person:two",
        confidence=0.8,
    )
    await catalog.record_mention(
        mention_text="Public retained alias",
        normalized_surface="public retained alias",
        entity_type="person",
        evidence_event_ids=["evt-keep"],
        evidence_text="Retained evidence text",
        resolved_entity_id="person:two",
        confidence=0.9,
    )
    await catalog.record_mention(
        mention_text="Temporary reference",
        normalized_surface="temporary reference",
        entity_type="person",
        evidence_event_ids=["evt-remove"],
        evidence_text="Temporary reference from deleted source",
        resolved_entity_id="person:independent",
        confidence=0.7,
    )
    await store.upsert_entity_facet(
        entity_id="person:one",
        entity_type="person",
        facet_name="role",
        facet_value="private-sole",
        evidence_event_ids=["evt-remove"],
        confidence=0.8,
        observed_at=100.0,
        source_type="conversation",
    )
    await store.upsert_entity_facet(
        entity_id="person:two",
        entity_type="person",
        facet_name="role",
        facet_value="private-mixed",
        evidence_event_ids=["evt-remove", "evt-keep"],
        confidence=0.8,
        observed_at=100.0,
        source_type="conversation",
    )

    result = await store.forget_source_events(["evt-remove"], reason="user_delete_event")

    mentions = await catalog.list_mentions(limit=10, offset=0)
    facets = await store.list_entity_facets(limit=10)
    assert len(mentions) == 2
    assert {item["mention_text"] for item in mentions} == {
        "Private mixed mention",
        "Public retained alias",
    }
    mixed_mention = next(
        item for item in mentions if item["mention_text"] == "Private mixed mention"
    )
    assert mixed_mention["evidence_text"] == "Private mixed mention"
    assert mixed_mention["evidence_event_ids"] == ["evt-keep"]
    entities = await catalog.list_entities(limit=10)
    retained_entity = next(item for item in entities if item["entity_id"] == "person:two")
    assert retained_entity["aliases"] == [
        "Independent label",
        "Private mixed mention",
    ]
    assert retained_entity["canonical_name"] == "Public retained alias"
    assert all(item["entity_id"] != "person:private" for item in entities)
    independent_entity = next(
        item for item in entities if item["entity_id"] == "person:independent"
    )
    assert independent_entity["canonical_name"] == "Independent person"
    assert independent_entity["aliases"] == ["Independent nickname"]
    assert (await catalog.resolve_alias("Private mixed mention"))["decision"] == "match"
    assert (await catalog.resolve_alias("Stale private alias"))["decision"] == "unresolved"
    assert await catalog.resolve_query_entities("Private Sole Canonical") == []
    assert len(facets) == 1
    assert facets[0]["facet_value"] == "private-mixed"
    assert facets[0]["evidence_event_ids"] == ["evt-keep"]
    assert facets[0]["confidence"] < 0.8
    assert result["entity_mentions"] == 3
    assert result["entity_aliases"] == 3
    assert result["entity_name_evidence"] == 5
    assert result["entity_catalog"] == 3
    assert result["entity_facets"] == 2


@pytest.mark.asyncio
async def test_source_event_forget_restores_retained_canonical_candidate(
    l2_store_with_schema,
) -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.initialize()
    await catalog.upsert_entity(
        canonical_name="Retained canonical",
        entity_type="topic",
        entity_id="topic:shared",
        source_event_ids=["evt-retained"],
    )
    await catalog.upsert_entity(
        canonical_name="Deleted canonical",
        entity_type="topic",
        entity_id="topic:shared",
        source_event_ids=["evt-deleted"],
    )
    await catalog.add_alias(
        entity_id="topic:shared",
        alias_text="Retained alternate",
        source_event_ids=["evt-retained"],
    )
    await catalog.add_alias(
        entity_id="topic:shared",
        alias_text="Deleted alternate",
        source_event_ids=["evt-deleted"],
    )

    await store.forget_source_events(["evt-deleted"], reason="user_delete_event")

    entity = (await catalog.list_entities(limit=10))[0]
    assert entity["canonical_name"] == "Retained canonical"
    assert entity["aliases"] == ["Retained alternate"]
    assert (await catalog.resolve_alias("Deleted alternate"))["decision"] == "unresolved"


@pytest.mark.asyncio
async def test_source_event_forget_fail_closes_unattributed_legacy_unicode_aliases(
    l2_store_with_schema,
) -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.initialize()
    await catalog.upsert_entity(
        canonical_name="Retained person",
        entity_type="person",
        entity_id="person:legacy-unicode",
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.executemany(
            """
            INSERT INTO entity_aliases(
                entity_id, alias_text, normalized_alias, confidence,
                is_independent, created_at, updated_at
            ) VALUES ('person:legacy-unicode', ?, ?, ?, 0, 1, 1)
            """,
            [
                ("STRASSE", "strasse", 0.9),
                ("MASSE", "masse", 0.9),
                ("Private orphan", "private orphan", 0.8),
            ],
        )
        await db.executemany(
            """
            INSERT INTO entity_mentions(
                mention_text, normalized_surface, entity_type,
                evidence_event_ids, evidence_text, resolved_entity_id,
                confidence, created_at
            ) VALUES (?, ?, 'person', ?, ?, 'person:legacy-unicode', ?, 2)
            """,
            [
                (
                    "Straße",
                    "Straße",
                    '["  evt-remove  "]',
                    "private unicode source",
                    0.9,
                ),
                (
                    "Maße",
                    "Maße",
                    '["evt-keep"]',
                    "retained unicode source",
                    0.7,
                ),
            ],
        )
        await db.commit()

    result = await store.forget_source_events(["evt-remove"], reason="user_delete_event")

    entity = (await catalog.list_entities(limit=10))[0]
    assert entity["entity_id"] == "person:legacy-unicode"
    assert entity["aliases"] == ["Maße"]
    assert (await catalog.resolve_alias("Straße"))["decision"] == "unresolved"
    assert (await catalog.resolve_alias("Maße", min_confidence=0.6))["decision"] == "match"
    assert result["entity_mentions"] == 1
    assert result["entity_aliases"] == 3


@pytest.mark.asyncio
async def test_tombstoned_source_cannot_replay_entity_names(
    l2_store_with_schema,
) -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.initialize()
    await catalog.upsert_entity(
        canonical_name="Independent canonical",
        entity_type="topic",
        entity_id="topic:independent",
    )
    await store.tombstone_source_events(
        ["evt-forgotten"],
        reason="user_delete_event",
    )

    await catalog.upsert_entity(
        canonical_name="Replayed canonical",
        entity_type="topic",
        entity_id="topic:independent",
        source_event_ids=["evt-forgotten"],
    )
    await catalog.add_alias(
        entity_id="topic:independent",
        alias_text="Replayed alias",
        source_event_ids=["evt-forgotten"],
    )
    mention_id = await catalog.record_mention(
        mention_text="Replayed mention",
        normalized_surface="replayed mention",
        entity_type="topic",
        evidence_event_ids=["evt-forgotten"],
        evidence_text="Replayed private evidence",
        resolved_entity_id="topic:independent",
        confidence=0.9,
    )

    entity = (await catalog.list_entities(limit=10))[0]
    assert entity["canonical_name"] == "Independent canonical"
    assert entity["aliases"] == []
    assert mention_id == 0
    assert await catalog.list_mentions(limit=10, offset=0) == []
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM entity_name_evidence") as cursor:
            assert await cursor.fetchone() == (0,)


@pytest.mark.asyncio
async def test_time_range_projection_block_prevents_entity_replay_without_tombstone(
    l2_store_with_schema,
) -> None:
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.initialize()
    await catalog.upsert_entity(
        canonical_name="Independent canonical",
        entity_type="topic",
        entity_id="topic:independent",
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_forget_operations(
                operation_id, selector_kind, selector_hash, selector_json,
                reason, created_at, updated_at
            ) VALUES (?, 'time_range', ?, '{}', 'user_forget_time_range', 1, 1)
            """,
            ("forget-time-1", "hash-time-1"),
        )
        await db.execute(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('episode_formation', 'time:hash-time-1', ?, 'forget-time-1', 1)
            """,
            ("evt-time-forgotten",),
        )
        await db.commit()

    await catalog.upsert_entity(
        canonical_name="Replayed canonical",
        entity_type="topic",
        entity_id="topic:independent",
        source_event_ids=["evt-time-forgotten"],
    )
    await catalog.add_alias(
        entity_id="topic:independent",
        alias_text="Replayed alias",
        source_event_ids=["evt-time-forgotten"],
    )
    mention_id = await catalog.record_mention(
        mention_text="Replayed mention",
        normalized_surface="replayed mention",
        entity_type="topic",
        evidence_event_ids=["evt-time-forgotten"],
        evidence_text="Replayed time-range evidence",
        resolved_entity_id="topic:independent",
        confidence=0.9,
    )

    entity = (await catalog.list_entities(limit=10))[0]
    assert entity["canonical_name"] == "Independent canonical"
    assert entity["aliases"] == []
    assert mention_id == 0
    assert await catalog.list_mentions(limit=10, offset=0) == []
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM entity_name_evidence") as cursor:
            assert await cursor.fetchone() == (0,)
        async with db.execute(
            "SELECT COUNT(*) FROM memory_source_event_tombstones WHERE event_id = ?",
            ("evt-time-forgotten",),
        ) as cursor:
            assert await cursor.fetchone() == (0,)


@pytest.mark.asyncio
async def test_time_range_projection_block_fail_closes_entity_facets(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await store.upsert_entity_facet(
        entity_id="person:time-facet",
        entity_type="person",
        facet_name="role",
        facet_value="blocked-existing",
        evidence_event_ids=["evt-time-facet"],
        confidence=0.8,
        observed_at=100.0,
        source_type="conversation",
    )
    await _insert_projection_block(
        store,
        event_id="evt-time-facet",
        target_id="time:facet-window",
    )

    assert await store.list_entity_facets(entity_id="person:time-facet") == []
    assert (
        await store.filter_entity_ids_by_facet(
            entity_ids=["person:time-facet"],
            facet_name="role",
            facet_values=["blocked-existing"],
        )
        == []
    )

    await store.upsert_entity_facet(
        entity_id="person:time-facet",
        entity_type="person",
        facet_name="role",
        facet_value="blocked-existing",
        evidence_event_ids=["evt-safe-after-block"],
        confidence=0.4,
        observed_at=150.0,
        source_type="conversation",
    )
    repaired = await store.list_entity_facets(entity_id="person:time-facet")
    assert len(repaired) == 1
    assert repaired[0]["evidence_event_ids"] == ["evt-safe-after-block"]
    assert repaired[0]["confidence"] == pytest.approx(0.4)

    blocked_facet_id = await store.upsert_entity_facet(
        entity_id="person:time-facet",
        entity_type="person",
        facet_name="role",
        facet_value="blocked-replay",
        evidence_event_ids=["evt-time-facet"],
        confidence=0.9,
        observed_at=200.0,
        source_type="conversation",
    )
    await store.upsert_entity_facet(
        entity_id="person:mixed-facet",
        entity_type="person",
        facet_name="role",
        facet_value="retained",
        evidence_event_ids=["evt-time-facet", "evt-safe-facet"],
        confidence=0.7,
        observed_at=200.0,
        source_type="conversation",
    )
    mixed = await store.list_entity_facets(entity_id="person:mixed-facet")
    assert len(mixed) == 1
    assert mixed[0]["evidence_event_ids"] == ["evt-safe-facet"]
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM entity_facets WHERE facet_id = ?",
            (blocked_facet_id,),
        ) as cursor:
            assert await cursor.fetchone() == (0,)

    await _insert_projection_block(
        store,
        event_id="evt-ordinary-facet",
        target_id="episode:ordinary-facet",
    )
    await store.upsert_entity_facet(
        entity_id="person:ordinary-facet",
        entity_type="person",
        facet_name="role",
        facet_value="still-active",
        evidence_event_ids=["evt-ordinary-facet"],
        confidence=0.8,
        observed_at=300.0,
        source_type="conversation",
    )
    ordinary = await store.list_entity_facets(entity_id="person:ordinary-facet")
    assert len(ordinary) == 1
    assert ordinary[0]["evidence_event_ids"] == ["evt-ordinary-facet"]


@pytest.mark.asyncio
async def test_time_range_projection_block_fail_closes_experience_sources(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await store.create_episode(
        episode_id="episode-time-source",
        status="active",
        time_start=100.0,
        time_end=200.0,
    )
    await store.add_episode_events(
        episode_id="episode-time-source",
        event_ids=["evt-time-experience"],
    )
    await store.create_experience(
        experience_id="experience-before-time-block",
        status="active",
        title="Existing experience",
        time_start=100.0,
        time_end=200.0,
    )
    await store.add_experience_members(
        experience_id="experience-before-time-block",
        members=[{"member_type": "episode", "member_id": "episode-time-source"}],
    )
    await store.replace_experience_chapters(
        experience_id="experience-before-time-block",
        chapters=[
            {
                "chapter_id": "chapter-time-source",
                "episode_ids": ["episode-time-source"],
                "event_ids": ["evt-time-experience"],
            }
        ],
    )
    await store.create_experience_draft(
        draft_id="draft-before-time-block",
        query_text="Existing draft",
        title="Existing draft",
        one_sentence_review="Existing draft review",
        time_start=100.0,
        time_end=200.0,
        chapters=[
            {
                "episode_ids": ["episode-time-source"],
                "event_ids": ["evt-time-experience"],
            }
        ],
        possible_evidence=[],
    )
    await store.create_experience_seed(
        seed_id="seed-before-time-block",
        seed_type="manual",
        status="accepted",
        title="Existing seed",
        source_ref_type="episode",
        source_ref_id="episode-time-source",
    )
    await store.add_experience_seed_evidence(
        seed_id="seed-before-time-block",
        evidence=[{"ref_type": "event", "ref_id": "evt-time-experience"}],
    )
    await store.create_experience(
        experience_id="experience-from-time-seed",
        status="active",
        title="Existing seeded experience",
        time_start=100.0,
        time_end=200.0,
        source_seed_id="seed-before-time-block",
    )
    await store.add_experience_members(
        experience_id="experience-from-time-seed",
        members=[{"member_type": "event", "member_id": "evt-safe-experience"}],
    )
    await store.replace_experience_chapters(
        experience_id="experience-from-time-seed",
        chapters=[{"episode_ids": [], "event_ids": ["evt-safe-experience"]}],
    )
    await store.create_experience_seed(
        seed_id="seed-active-target",
        seed_type="manual",
        status="accepted",
        title="Active target seed",
    )
    await store.create_experience(
        experience_id="experience-active-target",
        status="active",
        title="Active target experience",
        time_start=100.0,
        time_end=200.0,
    )

    await _insert_projection_block(
        store,
        event_id="evt-time-experience",
        target_id="time:experience-window",
    )

    assert await store.get_experience(experience_id="experience-before-time-block") is None
    assert await store.get_experience(experience_id="experience-from-time-seed") is None
    assert await store.list_experience_members(experience_id="experience-from-time-seed") == []
    assert await store.list_experience_chapters(experience_id="experience-from-time-seed") == []
    assert await store.list_experience_members(experience_id="experience-before-time-block") == []
    assert await store.count_experience_members(experience_id="experience-before-time-block") == 0
    assert await store.get_experience_draft(draft_id="draft-before-time-block") is None
    assert await store.list_experience_drafts() == []
    assert await store.get_experience_seed(seed_id="seed-before-time-block") is None
    assert [seed["seed_id"] for seed in await store.list_experience_seeds()] == [
        "seed-active-target"
    ]
    assert await store.list_experience_seed_evidence(seed_id="seed-before-time-block") == []

    with pytest.raises(ValueError, match="not active"):
        await store.update_experience_draft(
            draft_id="draft-before-time-block",
            title="Late draft update",
        )
    with pytest.raises(ValueError, match="no longer active"):
        await store.update_experience_seed(
            seed_id="seed-before-time-block",
            title="Late seed update",
        )
    with pytest.raises(ValueError, match="forgotten"):
        await store.add_experience_seed_evidence(
            seed_id="seed-active-target",
            evidence=[{"ref_type": "event", "ref_id": "evt-time-experience"}],
        )
    with pytest.raises(ValueError, match="forgotten"):
        await store.add_experience_members(
            experience_id="experience-active-target",
            members=[{"member_type": "event", "member_id": "evt-time-experience"}],
        )
    with pytest.raises(ValueError, match="not active"):
        await store.create_experience(
            experience_id="experience-after-time-seed",
            status="active",
            title="Late seeded experience",
            time_start=100.0,
            time_end=200.0,
            source_seed_id="seed-before-time-block",
        )
    with pytest.raises(ValueError, match="not active"):
        await store.update_experience(
            experience_id="experience-active-target",
            source_seed_id="seed-before-time-block",
        )
    with pytest.raises(ValueError, match="forgotten"):
        await store.replace_experience_chapters(
            experience_id="experience-active-target",
            chapters=[{"episode_ids": [], "event_ids": ["evt-time-experience"]}],
        )
    with pytest.raises(ValueError, match="forgotten"):
        await store.create_experience_draft(
            draft_id="draft-after-time-block",
            query_text="Late draft",
            title="Late draft",
            one_sentence_review="Must not persist",
            time_start=100.0,
            time_end=200.0,
            chapters=[{"episode_ids": [], "event_ids": ["evt-time-experience"]}],
            possible_evidence=[],
        )
    with pytest.raises(ValueError, match="forgotten"):
        await store.create_experience_seed(
            seed_id="seed-after-time-block",
            seed_type="manual",
            title="Late seed",
            source_ref_type="event",
            source_ref_id="evt-time-experience",
        )

    await store.create_episode(
        episode_id="episode-ordinary-target",
        status="active",
        time_start=300.0,
        time_end=400.0,
    )
    await store.add_episode_events(
        episode_id="episode-ordinary-target",
        event_ids=["evt-ordinary-experience"],
    )
    await _insert_projection_block(
        store,
        event_id="evt-ordinary-experience",
        target_id="episode-ordinary-target",
    )
    await store.create_experience_seed(
        seed_id="seed-ordinary-event",
        seed_type="manual",
        status="accepted",
        title="Direct event remains active",
        source_ref_type="event",
        source_ref_id="evt-ordinary-experience",
    )
    assert await store.get_experience_seed(seed_id="seed-ordinary-event") is not None
    assert (
        await store.add_experience_members(
            experience_id="experience-active-target",
            members=[{"member_type": "event", "member_id": "evt-ordinary-experience"}],
        )
        == 1
    )
    with pytest.raises(ValueError, match="not active"):
        await store.create_experience_seed(
            seed_id="seed-ordinary-episode",
            seed_type="manual",
            title="Blocked episode",
            source_ref_type="episode",
            source_ref_id="episode-ordinary-target",
        )


@pytest.mark.asyncio
async def test_time_range_projection_block_fail_closes_projection_queue(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await _insert_projection_block(
        store,
        event_id="evt-time-before-enqueue",
        target_id="time:queue-before-enqueue",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert not await store.enqueue_projection_job(
            event_id="evt-time-before-enqueue",
            source="chat",
            event_type="UserMessage",
        )

    assert await store.enqueue_projection_job(
        event_id="evt-time-pending",
        source="chat",
        event_type="UserMessage",
    )
    await _insert_projection_block(
        store,
        event_id="evt-time-pending",
        target_id="time:queue-pending",
    )
    assert await store.claim_projection_jobs(consumer_name="test-worker", limit=10) == []
    assert (
        await store.claim_ready_projection_jobs(
            consumer_name="test-worker",
            limit=10,
        )
        == []
    )
    assert (await store.get_projection_backlog_stats())["pending"] == 0

    assert await store.enqueue_projection_job(
        event_id="evt-time-queued",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(consumer_name="test-worker", limit=1)
    assert [row["event_id"] for row in claimed] == ["evt-time-queued"]
    assert (
        await store.bind_projection_job_batch(
            [_projection_lease(claimed[0])],
            consumer_name="test-worker",
        )
        == 1
    )
    await _insert_projection_block(
        store,
        event_id="evt-time-queued",
        target_id="time:queue-queued",
    )
    assert (
        await store.mark_projection_jobs_running(
            [_projection_lease(claimed[0])],
            consumer_name="test-worker",
        )
        == 0
    )

    await _insert_projection_block(
        store,
        event_id="evt-ordinary-queue",
        target_id="episode-ordinary-queue",
    )
    assert await store.enqueue_projection_job(
        event_id="evt-ordinary-queue",
        source="chat",
        event_type="UserMessage",
    )
    claimed = await store.claim_projection_jobs(consumer_name="test-worker", limit=10)
    assert [row["event_id"] for row in claimed] == ["evt-ordinary-queue"]


@pytest.mark.asyncio
async def test_forgotten_source_event_cannot_create_assertion_or_edge_correction(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _assertion(store, value="Hangzhou", event_ids=["evt-assertion"])
    edge_id = await _edge(store, object_id="place:hangzhou", event_ids=["evt-edge"])
    await store.forget_source_events(["evt-deleted-feedback"], reason="user_delete_event")

    for request_id in ("assertion-deleted-source-1", "assertion-deleted-source-2"):
        with pytest.raises(MemoryCorrectionConflictError) as assertion_error:
            await store.apply_assertion_correction(
                assertion_id=assertion_id,
                request_id=request_id,
                actor_id="user:u1",
                correction_kind=CorrectionKind.RECORD_ERROR,
                replacement_value="Shanghai",
                source_event_id="evt-deleted-feedback",
            )
        assert assertion_error.value.code == "correction_source_event_forgotten"

    for request_id in ("edge-deleted-source-1", "edge-deleted-source-2"):
        with pytest.raises(MemoryCorrectionConflictError) as edge_error:
            await store.apply_relationship_correction(
                triple_id=edge_id,
                request_id=request_id,
                actor_id="user:u1",
                correction_kind=CorrectionKind.RECORD_ERROR,
                replacement={"object_id": "place:shanghai", "object_type": "place"},
                source_event_id="evt-deleted-feedback",
            )
        assert edge_error.value.code == "correction_source_event_forgotten"


@pytest.mark.asyncio
async def test_time_range_blocked_source_cannot_create_correction(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _assertion(store, value="Hangzhou", event_ids=["evt-assertion"])
    edge_id = await _edge(store, object_id="place:hangzhou", event_ids=["evt-edge"])
    await _insert_projection_block(
        store,
        event_id="evt-time-feedback",
        target_id="time:correction-source",
    )

    with pytest.raises(MemoryCorrectionConflictError) as assertion_error:
        await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="assertion-time-blocked-source",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="Shanghai",
            source_event_id="evt-time-feedback",
        )
    assert assertion_error.value.code == "correction_source_event_forgotten"

    with pytest.raises(MemoryCorrectionConflictError) as edge_error:
        await store.apply_relationship_correction(
            triple_id=edge_id,
            request_id="edge-time-blocked-source",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": "place:shanghai", "object_type": "place"},
            source_event_id="evt-time-feedback",
        )
    assert edge_error.value.code == "correction_source_event_forgotten"

    await _insert_projection_block(
        store,
        event_id="evt-ordinary-feedback",
        target_id="episode-ordinary-feedback",
    )
    assertion_result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="assertion-ordinary-block-source",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
        source_event_id="evt-ordinary-feedback",
    )
    edge_result = await store.apply_relationship_correction(
        triple_id=edge_id,
        request_id="edge-ordinary-block-source",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
        source_event_id="evt-ordinary-feedback",
    )
    assert assertion_result is not None
    assert edge_result is not None


@pytest.mark.asyncio
async def test_forgetting_correction_source_restores_record_error_without_replacement(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    assertion_id = await _assertion(store, value="Hangzhou", event_ids=["evt-assertion"])
    edge_id = await _edge(store, object_id="place:hangzhou", event_ids=["evt-edge"])
    assertion_before = await store.get_tom_assertion(assertion_id=assertion_id)
    edge_before = await store.get_relationship(triple_id=edge_id)
    assert assertion_before is not None and edge_before is not None
    assertion_result = await store.apply_assertion_correction(
        assertion_id=assertion_id,
        request_id="assertion-no-replacement-source",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        source_event_id="evt-assertion-feedback",
    )
    edge_result = await store.apply_relationship_correction(
        triple_id=edge_id,
        request_id="edge-no-replacement-source",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        source_event_id="evt-edge-feedback",
    )
    assert assertion_result is not None and edge_result is not None

    await store.forget_source_events(
        ["evt-assertion-feedback", "evt-edge-feedback"],
        reason="user_delete_event",
    )

    assertion = await store.get_tom_assertion(assertion_id=assertion_id)
    edge = await store.get_relationship(triple_id=edge_id)
    assert assertion is not None and assertion["status"] == assertion_before["status"]
    assert edge is not None and edge["status"] == edge_before["status"]
    async with aiosqlite.connect(store.db_path) as db:
        async with db.execute("""
            SELECT state, reverted_by,
                   (SELECT COUNT(*) FROM memory_correction_rules AS rules
                    WHERE rules.correction_id = corrections.correction_id
                      AND rules.active = 1)
            FROM memory_corrections AS corrections
            WHERE source_event_id IN ('evt-assertion-feedback', 'evt-edge-feedback')
            ORDER BY target_kind
            """) as cursor:
            rows = await cursor.fetchall()
    assert rows == [
        ("reverted", "system:forgotten_source_event", 0),
        ("reverted", "system:forgotten_source_event", 0),
    ]


@pytest.mark.asyncio
async def test_forgetting_assertion_correction_source_preserves_independent_merged_claim(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    for entity_id in ("person:winner", "person:loser"):
        await catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name="Same person",
            entity_type="person",
        )
    now = time.time() - 60
    ordinary_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "person:winner",
            "entity_type": "person",
            "trait_family": "preference_profile",
            "trait_name": "favorite_city",
            "trait_value": "Shanghai",
            "confidence_score": 0.8,
            "evidence_events": ["evt-independent"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": "persistent",
        }
    )
    source_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "person:loser",
            "entity_type": "person",
            "trait_family": "preference_profile",
            "trait_name": "favorite_city",
            "trait_value": "Hangzhou",
            "confidence_score": 0.8,
            "evidence_events": ["evt-source"],
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": now + 1,
            "last_validated_at": now + 1,
            "temporal_scope": "persistent",
        }
    )
    result = await store.apply_assertion_correction(
        assertion_id=source_id,
        request_id="correct-shared-assertion",
        actor_id="user:self",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement_value="Shanghai",
        source_event_id="evt-correction-feedback",
    )
    assert result is not None
    await L2EntityMaintenance(db_path=store.db_path)._merge_entity_into(
        "person:winner",
        "person:loser",
    )

    await store.forget_source_events(
        ["evt-correction-feedback"],
        reason="user_delete_event",
    )

    current = await store.list_current_assertions(
        entity_id="person:winner",
        limit=20,
    )
    assert [(item["assertion_id"], item["trait_value"]) for item in current] == [
        (ordinary_id, "Shanghai"),
    ]
    assert "evt-independent" in current[0]["evidence_events"]


@pytest.mark.asyncio
async def test_assertion_correction_chain_rebases_after_sources_are_forgotten(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    now = time.time()
    original_id = await _assertion(store, value="A", event_ids=["evt-original"])
    first = await store.apply_assertion_correction(
        assertion_id=original_id,
        request_id="assertion-chain-a-b",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="B",
        effective_at=now - 30,
        source_event_id="evt-source-b",
    )
    assert first is not None
    second = await store.apply_assertion_correction(
        assertion_id=first["current_assertion"]["assertion_id"],
        request_id="assertion-chain-b-c",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement_value="C",
        effective_at=now - 10,
        source_event_id="evt-source-c",
    )
    assert second is not None

    await store.forget_source_events(["evt-source-b"], reason="user_delete_event")
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["trait_value"] for item in current] == ["C"]

    await store.forget_source_events(["evt-source-c"], reason="user_delete_event")
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [original_id]
    assert current[0]["trait_value"] == "A"


@pytest.mark.asyncio
async def test_relationship_correction_chain_rebases_after_sources_are_forgotten(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    now = time.time()
    original_id = await _edge(store, object_id="place:a", event_ids=["evt-original"])
    first = await store.apply_relationship_correction(
        triple_id=original_id,
        request_id="edge-chain-a-b",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:b", "object_type": "place"},
        effective_at=now - 30,
        source_event_id="evt-source-b",
    )
    assert first is not None
    second = await store.apply_relationship_correction(
        triple_id=first["current_relationship"]["triple_id"],
        request_id="edge-chain-b-c",
        actor_id="user:u1",
        correction_kind=CorrectionKind.SITUATION_CHANGED,
        replacement={"object_id": "place:c", "object_type": "place"},
        effective_at=now - 10,
        source_event_id="evt-source-c",
    )
    assert second is not None

    await store.forget_source_events(["evt-source-b"], reason="user_delete_event")
    current = await store.list_current_relationships(subject_id="user:u1")
    assert [item["object_id"] for item in current] == ["place:c"]

    await store.forget_source_events(["evt-source-c"], reason="user_delete_event")
    current = await store.list_current_relationships(subject_id="user:u1")
    assert [item["triple_id"] for item in current] == [original_id]
    assert current[0]["object_id"] == "place:a"
