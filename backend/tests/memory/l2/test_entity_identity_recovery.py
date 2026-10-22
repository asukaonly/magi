"""Recover ordinary catalog damage without weakening identity erasure or fencing."""

from __future__ import annotations

import json
from types import SimpleNamespace

import aiosqlite
import pytest

from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.identity import scoped_entity_id
from magi.memory.l2.entities.identity_repository import EntityIdentityUnavailableError
from magi.memory.l2.entities.maintenance import L2EntityMaintenance, L2EntityMaintenanceStats
from magi.memory.l2.models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.projection.errors import ProjectionAttemptFencedError
from magi.memory.l2.projection.entity_links import begin_event_entity_link_projection_clear
from magi.memory.shared_clear import clear_shared_auxiliary_memory


async def _lease(store, event_id="event-1"):
    await store.enqueue_projection_job(event_id=event_id, source="source", event_type="event")
    row = (await store.claim_projection_jobs(consumer_name="repair", limit=1))[0]
    lease = L2ProjectionLease.from_dict(row)
    assert await store.bind_projection_job_batch([lease], consumer_name="repair") == 1
    assert await store.mark_projection_jobs_running([lease], consumer_name="repair") == 1
    return lease


def _values(event_id="event-1"):
    namespace = f"source:event:{event_id}"
    return dict(
        entity_id=scoped_entity_id("software", namespace, "0"),
        entity_type="software",
        canonical_name="Private synthetic source name",
        source_namespace=namespace,
        source_key="0",
        source_event_ids=[event_id],
    )


async def _damage(catalog, entity_id):
    async with aiosqlite.connect(catalog.db_path) as db:
        await db.execute("DELETE FROM entity_name_evidence WHERE entity_id=?", (entity_id,))
        await db.execute("DELETE FROM entity_catalog WHERE entity_id=?", (entity_id,))
        await db.commit()


async def _operation(db, entity_id):
    await db.execute(
        """INSERT INTO entity_identity_operations VALUES (
            'operation', 'request', 'fingerprint', 'type_correction', ?, ?,
            'software', 'organization', 'user', '{}', 1)""",
        (entity_id, entity_id),
    )


@pytest.mark.asyncio
async def test_maintenance_preserves_bound_identity_and_replay(l2_store_with_schema):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    values = _values()
    lease = await _lease(store)
    await catalog.upsert_entity(**values, projection_leases=[lease])
    maintenance = L2EntityMaintenance(db_path=store.db_path)
    stats = L2EntityMaintenanceStats()
    await maintenance._prune_orphan_low_mention_entities(stats, min_mentions=2)
    assert stats.orphans_pruned == 0
    assert not stats.errors
    assert await catalog.upsert_entity(**values, projection_leases=[lease]) == values["entity_id"]
    assert len(await catalog.list_entities()) == 1


@pytest.mark.asyncio
async def test_legacy_damage_restores_original_id_idempotently_after_reopen(l2_store_with_schema):
    store = l2_store_with_schema
    values = _values()
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.upsert_entity(**values)
    await _damage(catalog, values["entity_id"])
    await catalog.close()
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    lease = await _lease(store)
    for _ in range(2):
        assert (
            await catalog.upsert_entity(**values, projection_leases=[lease]) == values["entity_id"]
        )
    async with aiosqlite.connect(store.db_path) as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM entity_source_bindings")).fetchone())[
            0
        ] == 1
        assert (await (await db.execute("SELECT COUNT(*) FROM entity_name_evidence")).fetchone())[
            0
        ] == 1
        assert (await (await db.execute("SELECT COUNT(*) FROM entity_catalog")).fetchone())[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "no_lease",
        "no_binding_proof",
        "empty_evidence",
        "independent",
        "unleased_evidence",
        "different_id",
        "unknown_allocation",
        "redirect_source",
        "redirect_target",
        "decision",
        "review",
        "forget",
    ],
)
async def test_missing_identity_requires_proven_source_and_no_governance(
    l2_store_with_schema, case
):
    store = l2_store_with_schema
    values = _values()
    if case == "unknown_allocation":
        values["entity_id"] = "opaque:allocation"
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.upsert_entity(**values)
    await _damage(catalog, values["entity_id"])
    lease = await _lease(store)
    async with aiosqlite.connect(store.db_path) as db:
        entity_id = values["entity_id"]
        if case == "redirect_source":
            await db.execute(
                "INSERT INTO entity_identity_redirects VALUES (?, 'missing', 'op')", (entity_id,)
            )
        if case == "redirect_target":
            await db.execute(
                "INSERT INTO entity_identity_redirects VALUES ('old', ?, 'op')", (entity_id,)
            )
        if case == "decision":
            await _operation(db, entity_id)
        if case == "review":
            await db.execute(
                "INSERT INTO entity_identity_reviews(review_id,entity_id,proposed_type,created_at,updated_at) VALUES ('review',?,'brand',1,1)",
                (entity_id,),
            )
        await db.commit()
    if case == "forget":
        await catalog.forget_entity_catalog(values["entity_id"])
    if case == "no_binding_proof":
        values.pop("source_namespace")
        values.pop("source_key")
    if case == "different_id":
        values["entity_id"] = "another-id"
    if case == "empty_evidence":
        values["source_event_ids"] = []
    if case == "independent":
        values["source_event_ids"] = None
    if case == "unleased_evidence":
        values["source_event_ids"] = ["other-event"]
    with pytest.raises(EntityIdentityUnavailableError) as caught:
        await catalog.upsert_entity(
            **values, projection_leases=[] if case == "no_lease" else [lease]
        )
    assert "Private synthetic" not in str(caught.value)
    assert await catalog.list_entities() == []


@pytest.mark.asyncio
async def test_stale_attempt_and_full_clear_fence_recovery(l2_store_with_schema):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    values = _values()
    await catalog.upsert_entity(**values)
    await _damage(catalog, values["entity_id"])
    lease = await _lease(store)
    stale = L2ProjectionLease(
        event_id=lease.event_id, lease_token="stale", attempt_count=lease.attempt_count
    )
    with pytest.raises(ProjectionAttemptFencedError):
        await catalog.upsert_entity(**values, projection_leases=[stale])
    assert await catalog.list_entities() == []
    generation = await begin_event_entity_link_projection_clear(store.db_path)
    await store.clear(entity_link_clear_generation=generation)
    await clear_shared_auxiliary_memory(store.db_path)
    with pytest.raises(ProjectionAttemptFencedError):
        await catalog.upsert_entity(**values, projection_leases=[lease])
    assert await catalog.list_entities() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "barrier", ["entity_projection", "episode_formation", "surface", "event_tombstone"]
)
async def test_source_barriers_prevent_reconstruction(l2_store_with_schema, barrier):
    store = l2_store_with_schema
    values = _values()
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    await catalog.upsert_entity(**values)
    await _damage(catalog, values["entity_id"])
    lease = await _lease(store)
    async with aiosqlite.connect(store.db_path) as db:
        if barrier == "event_tombstone":
            await db.execute(
                "INSERT INTO memory_source_event_tombstones VALUES ('event-1','forgotten',1)"
            )
        elif barrier == "surface":
            await db.execute(
                "INSERT INTO memory_entity_projection_identity_blocks VALUES (?, 'event-1', ?, 'software', 'op', 1)",
                (values["entity_id"], values["canonical_name"].casefold()),
            )
        else:
            target = values["entity_id"] if barrier == "entity_projection" else "time:range"
            await db.execute(
                "INSERT INTO memory_projection_blocks VALUES (?, ?, 'event-1', 'op', 1)",
                (barrier, target),
            )
        await db.commit()
    with pytest.raises((EntityIdentityUnavailableError, ProjectionAttemptFencedError)):
        await catalog.upsert_entity(**values, projection_leases=[lease])
    assert await catalog.list_entities() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "anchor", ["pending", "rejected", "applied", "operation", "redirect", "publication", "none"]
)
async def test_pruning_preserves_governance_anchors_and_true_orphans(l2_store_with_schema, anchor):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    entity_id = "synthetic-id"
    await catalog.upsert_entity(
        entity_id=entity_id,
        canonical_name="Candidate",
        entity_type="software",
        source_event_ids=["event-1"],
    )
    async with aiosqlite.connect(store.db_path) as db:
        if anchor in {"pending", "rejected", "applied"}:
            await db.execute(
                "INSERT INTO entity_identity_reviews(review_id,entity_id,proposed_type,status,created_at,updated_at) VALUES ('review',?,'brand',?,1,1)",
                (entity_id, anchor),
            )
        if anchor == "operation":
            await _operation(db, entity_id)
        if anchor == "redirect":
            await db.execute(
                "INSERT INTO entity_identity_redirects VALUES ('old', ?, 'op')", (entity_id,)
            )
        if anchor == "publication":
            await db.execute(
                """INSERT INTO l2_event_entity_link_outbox(
                event_id,revision,batch_key,lease_token,attempt_count,clear_generation,
                desired_links_json,state,created_at,updated_at
            ) VALUES ('event-1',1,'batch','lease',1,0,?,'ready',1,1)""",
                (json.dumps([{"entity_id": entity_id}]),),
            )
        await db.commit()
    stats = L2EntityMaintenanceStats()
    await L2EntityMaintenance(db_path=store.db_path)._prune_orphan_low_mention_entities(
        stats, min_mentions=2
    )
    assert not stats.errors
    assert stats.orphans_pruned == (1 if anchor == "none" else 0)
    assert len(await catalog.list_entities()) == (0 if anchor == "none" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("clear", ["catalog", "shared"])
async def test_direct_forget_retains_private_free_barrier_until_full_clear(
    l2_store_with_schema, clear
):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    values = _values()
    await catalog.upsert_entity(**values)
    await catalog.forget_entity_catalog(values["entity_id"])
    await catalog.forget_entity_catalog(values["entity_id"])
    async with aiosqlite.connect(store.db_path) as db:
        rows = await (await db.execute("SELECT * FROM entity_identity_tombstones")).fetchall()
        assert len(rows) == 1 and rows[0][0] == values["entity_id"]
        assert "Private synthetic" not in str(rows)
    with pytest.raises(EntityIdentityUnavailableError):
        await catalog.upsert_entity(**values)
    if clear == "catalog":
        await catalog.clear()
    else:
        await clear_shared_auxiliary_memory(store.db_path)
    assert await catalog.upsert_entity(**values) == values["entity_id"]
    async with aiosqlite.connect(store.db_path) as db:
        assert (
            await (await db.execute("SELECT COUNT(*) FROM entity_identity_tombstones")).fetchone()
        )[0] == 0


@pytest.mark.asyncio
async def test_unavailable_identity_stops_automatic_retries_but_can_be_requeued(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    lease = await _lease(store)
    pipeline = L2Pipeline(
        cognition_store=store, entity_catalog=SimpleNamespace(), llm_service=SimpleNamespace()
    )
    job = L2BatchJob(
        job_id="job",
        bucket_key="owner",
        events=[{"event_id": lease.event_id}],
        flush_reason="test",
        estimated_tokens=1,
        projection_leases=[lease],
    )
    await pipeline._fail_extract_job(
        job, EntityIdentityUnavailableError("unresolved_or_governed_identity")
    )
    async with aiosqlite.connect(store.db_path) as db:
        row = await (
            await db.execute(
                "SELECT status, attempt_count, next_retry_at,last_error FROM l2_projection_jobs"
            )
        ).fetchone()
    assert row[:3] == ("failed", 1, None)
    assert "unresolved_or_governed_identity" in row[3]
    result = await store.retry_failed_projection_jobs(limit=100)
    assert result["queued_count"] == 1


@pytest.mark.asyncio
async def test_new_evidence_can_relearn_source_identity_after_event_forgetting(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    values = _values()
    values.update(source_namespace="source", source_key="stable-object")
    values["entity_id"] = scoped_entity_id("software", "source", "stable-object")
    await catalog.upsert_entity(**values)
    await store.forget_source_events(["event-1"], reason="user_request")
    assert await catalog.list_entities() == []
    new_lease = await _lease(store, "event-2")
    values["source_event_ids"] = ["event-2"]
    assert (
        await catalog.upsert_entity(**values, projection_leases=[new_lease]) == values["entity_id"]
    )
    await catalog.forget_entity_catalog(values["entity_id"])
    with pytest.raises(EntityIdentityUnavailableError):
        await catalog.upsert_entity(**values, projection_leases=[new_lease])


@pytest.mark.asyncio
async def test_redirect_chain_resolves_live_target_but_never_recreates_missing_target(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    values = _values()
    await catalog.upsert_entity(**values)
    await catalog.upsert_entity(
        entity_id="survivor", canonical_name="Explicit survivor", entity_type="organization"
    )
    await _damage(catalog, values["entity_id"])
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "INSERT INTO entity_identity_redirects VALUES (?,'middle','merge-1')",
            (values["entity_id"],),
        )
        await db.execute(
            "INSERT INTO entity_identity_redirects VALUES ('middle','survivor','merge-2')"
        )
        await db.commit()
    lease = await _lease(store)
    assert await catalog.upsert_entity(**values, projection_leases=[lease]) == "survivor"
    assert (await catalog.list_entities())[0]["entity_type"] == "organization"
    await _damage(catalog, "survivor")
    with pytest.raises(EntityIdentityUnavailableError):
        await catalog.upsert_entity(**values, projection_leases=[lease])
    assert await catalog.list_entities() == []


@pytest.mark.asyncio
async def test_direct_forget_of_unbound_identity_also_prevents_recreation(l2_store_with_schema):
    catalog = L2EntityCatalog(db_path=l2_store_with_schema.db_path, vector_enabled=False)
    values = dict(
        entity_id="independent", canonical_name="Private independent", entity_type="software"
    )
    await catalog.upsert_entity(**values)
    await catalog.forget_entity_catalog("independent")
    with pytest.raises(EntityIdentityUnavailableError):
        await catalog.upsert_entity(**values)
    assert await catalog.list_entities() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("governance", ["operation", "redirect_target"])
async def test_missing_governed_identity_cannot_be_inserted_without_binding(
    l2_store_with_schema, governance
):
    catalog = L2EntityCatalog(db_path=l2_store_with_schema.db_path, vector_enabled=False)
    async with aiosqlite.connect(catalog.db_path) as db:
        if governance == "operation":
            await _operation(db, "missing-governed")
        else:
            await db.execute(
                "INSERT INTO entity_identity_redirects VALUES ('old','missing-governed','merge')"
            )
        await db.commit()
    with pytest.raises(EntityIdentityUnavailableError):
        await catalog.upsert_entity(
            entity_id="missing-governed", canonical_name="New model label", entity_type="software"
        )
    assert await catalog.list_entities() == []
