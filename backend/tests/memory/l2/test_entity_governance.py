"""Governed identity changes preserve identity, references and user intent."""

import asyncio
import json

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.governance import EntityIdentityService
from magi.memory.l2.entities.governance_models import EntityChangeCommand, EntityChangeApplyRequest
from magi.memory.l2.entities.governance_read import EntityIdentityConflictError, query_rows
from magi.memory.l2.store import L2CognitionStore


@pytest.fixture
async def identity(tmp_path):
    catalog = L2EntityCatalog(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await catalog.upsert_entity(
        entity_id="other:apple", canonical_name="Apple", entity_type="other"
    )
    return EntityIdentityService(catalog)


async def apply_preview(service, command, request_id="test-operation"):
    preview = await service.preview(command)
    request = EntityChangeApplyRequest(
        command=command, expected_fingerprint=preview.fingerprint, request_id=request_id
    )
    return request, await service.apply(request, actor_id="user:self")


@pytest.mark.asyncio
async def test_type_correction_keeps_id_updates_assertions_and_queues_subjects(identity):
    store = L2CognitionStore(db_path=identity.db_path)
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:self",
            "entity_type": "user",
            "trait_name": "preference",
            "trait_value": "like",
            "target_entity_id": "other:apple",
            "target_entity_type": "other",
            "evidence_events": ["e1"],
            "confidence_score": 0.95,
            "last_validated_at": 1.0,
            "first_inferred_at": 1.0,
            "temporal_scope": "persistent",
            "volatility_index": 0.1,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "trait_family": "preference_profile",
            "validation_state": "stable",
        }
    )
    request, result = await apply_preview(
        identity,
        EntityChangeCommand(kind="type_correction", entity_id="other:apple", new_type="food"),
    )
    assert result.entity_id == "other:apple"
    assert (await identity.catalog.list_entities())[0]["entity_type"] == "food"
    assertions = await store.list_tom_assertions(limit=20)
    assert assertions[0]["target_entity_type"] == "food"
    assert assertions[0]["target_entity_id"] == "other:apple"
    async with sqlite_connection_async(identity.db_path) as db:
        jobs = await query_rows(db, "SELECT * FROM memory_derivation_jobs")
        assert {row["job_kind"] for row in jobs if row["target_key"] == "user:self"} == {
            "snapshot",
            "profile",
            "portrait",
            "l3_insight",
        }
        assert all(
            row["entity_operation_id"] == result.operation_id and row["correction_id"] is None
            for row in jobs
        )
    assert await identity.apply(request, actor_id="user:self") == result


@pytest.mark.asyncio
async def test_preview_is_read_only_and_stale_apply_is_rejected(identity):
    command = EntityChangeCommand(kind="type_correction", entity_id="other:apple", new_type="food")
    preview = await identity.preview(command)
    assert (await identity.catalog.list_entities())[0]["entity_type"] == "other"
    await identity.catalog.add_alias(entity_id="other:apple", alias_text="苹果")
    with pytest.raises(EntityIdentityConflictError, match="changed after preview"):
        await identity.apply(
            EntityChangeApplyRequest(
                command=command, expected_fingerprint=preview.fingerprint, request_id="stale"
            ),
            actor_id="user:self",
        )
    assert (await identity.catalog.list_entities())[0]["entity_type"] == "other"


@pytest.mark.asyncio
async def test_concurrent_apply_has_one_operation_and_payload_reuse_is_rejected(identity):
    command = EntityChangeCommand(kind="type_correction", entity_id="other:apple", new_type="food")
    preview = await identity.preview(command)
    request = EntityChangeApplyRequest(
        command=command, expected_fingerprint=preview.fingerprint, request_id="once"
    )
    first, second = await asyncio.gather(
        identity.apply(request, actor_id="user:self"), identity.apply(request, actor_id="user:self")
    )
    assert first == second
    with pytest.raises(EntityIdentityConflictError, match="another change"):
        await identity.apply(
            request.model_copy(
                update={
                    "command": EntityChangeCommand(
                        kind="type_correction", entity_id="other:apple", new_type="brand"
                    )
                }
            ),
            actor_id="user:self",
        )


@pytest.mark.asyncio
async def test_merge_follows_explicit_choice_and_flattens_redirects(identity):
    await identity.catalog.upsert_entity(
        entity_id="organization:apple", canonical_name="Apple", entity_type="organization"
    )
    await identity.catalog.upsert_entity(
        entity_id="group:apple", canonical_name="Apple", entity_type="group"
    )
    audit = await identity.audit()
    assert len(audit.groups[0].entities) == 3
    _, result = await apply_preview(
        identity,
        EntityChangeCommand(
            kind="merge", entity_id="other:apple", target_entity_id="organization:apple"
        ),
    )
    assert result.entity_id == "organization:apple"
    assert len(await identity.catalog.list_entities()) == 2
    assert (await identity.catalog.list_entities(entity_ids=["other:apple"]))[0][
        "entity_id"
    ] == result.entity_id
    # A second explicit merge keeps references to both predecessors resolvable.
    await apply_preview(
        identity,
        EntityChangeCommand(
            kind="merge", entity_id="organization:apple", target_entity_id="group:apple"
        ),
        "second",
    )
    assert (await identity.catalog.list_entities(entity_ids=["other:apple"]))[0][
        "entity_id"
    ] == "group:apple"


@pytest.mark.asyncio
async def test_failed_derivation_enqueue_rolls_back_identity_and_audit(identity, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr("magi.memory.l2.entities.governance.enqueue_identity_derivations", fail)
    with pytest.raises(RuntimeError, match="injected transaction"):
        await apply_preview(
            identity,
            EntityChangeCommand(kind="type_correction", entity_id="other:apple", new_type="food"),
        )
    assert (await identity.catalog.list_entities())[0]["entity_type"] == "other"
    async with sqlite_connection_async(identity.db_path) as db:
        assert not await query_rows(db, "SELECT * FROM entity_identity_operations")


@pytest.mark.asyncio
async def test_review_rejection_and_confirmation_are_versioned(identity):
    await identity.catalog.record_mention(
        mention_text="Apple",
        normalized_surface="apple",
        entity_type="brand",
        evidence_event_ids=["e1"],
        evidence_text="Apple",
        resolved_entity_id="other:apple",
        confidence=0.95,
    )
    review = (await identity.list_reviews()).items[0]
    with pytest.raises(EntityIdentityConflictError):
        await identity.reject_review(review.review_id, expected_version=review.version + 1)
    request, _ = await apply_preview(
        identity,
        EntityChangeCommand(
            kind="type_correction",
            entity_id="other:apple",
            new_type="brand",
            review_id=review.review_id,
        ),
    )
    assert (await identity.list_reviews()).total == 0
    async with sqlite_connection_async(identity.db_path) as db:
        assert (await query_rows(db, "SELECT status FROM entity_identity_reviews"))[0][
            "status"
        ] == "applied"


@pytest.mark.asyncio
async def test_identity_change_fences_whole_inflight_batches(identity):
    async with sqlite_connection_async(identity.db_path) as db:
        await db.execute(
            "INSERT INTO l2_projection_jobs(event_id, source, event_type, status, attempt_count, lease_token, batch_attempt_key, created_at, updated_at) VALUES ('e-running','chat','message','running',1,'old-lease','l2pa_old',1,1)"
        )
        await db.commit()
    await apply_preview(
        identity,
        EntityChangeCommand(kind="type_correction", entity_id="other:apple", new_type="food"),
    )
    async with sqlite_connection_async(identity.db_path) as db:
        row = (await query_rows(db, "SELECT * FROM l2_projection_jobs"))[0]
        assert row["status"] == "pending"
        assert row["lease_token"] is None and row["batch_attempt_key"] is None
        assert row["attempt_count"] == 0


@pytest.mark.asyncio
async def test_forgotten_source_removes_type_proposal_and_stales_preview(identity):
    await identity.catalog.record_mention(
        mention_text="Apple",
        normalized_surface="apple",
        entity_type="food",
        evidence_event_ids=["e1"],
        evidence_text="Apple",
        resolved_entity_id="other:apple",
        confidence=0.95,
    )
    review = (await identity.list_reviews()).items[0]
    preview = await identity.preview(
        EntityChangeCommand(
            kind="type_correction",
            entity_id="other:apple",
            new_type="food",
            review_id=review.review_id,
        )
    )
    assert preview.evidence_event_ids == {"other:apple": ["e1"]}
    from magi.memory.l2.entities.governance_read import EntityIdentityNotFoundError

    store = L2CognitionStore(db_path=identity.db_path)
    await store.forget_source_events(["e1"], reason="user_delete")
    assert (await identity.list_reviews()).total == 0
    with pytest.raises(EntityIdentityNotFoundError):
        await identity.apply(
            EntityChangeApplyRequest(
                command=preview.command,
                expected_fingerprint=preview.fingerprint,
                request_id="forgotten-review",
            ),
            actor_id="user:self",
        )


@pytest.mark.asyncio
async def test_identity_jobs_preserve_profile_before_portrait_dependency(identity):
    from magi.memory.l2.corrections.repository import MemoryCorrectionRepository
    from magi.memory.l2.entities.governance_write import enqueue_identity_derivations

    _, result = await apply_preview(
        identity,
        EntityChangeCommand(kind="type_correction", entity_id="other:apple", new_type="food"),
    )
    async with sqlite_connection_async(identity.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        await enqueue_identity_derivations(
            db,
            db_path=identity.db_path,
            state={"subjects": ["user:self"], "relationships": [], "assertions": []},
            operation_id=result.operation_id,
            now=2,
        )
        await db.execute(
            "UPDATE memory_derivation_jobs SET status='completed' WHERE job_kind != 'portrait'"
        )
        await db.execute(
            "UPDATE memory_derivation_jobs SET status='failed', next_retry_at=NULL WHERE job_kind='profile'"
        )
        await db.commit()
    assert await MemoryCorrectionRepository(identity.db_path).claim_next_derivation_job() is None
    async with sqlite_connection_async(identity.db_path) as db:
        row = (
            await query_rows(db, "SELECT * FROM memory_derivation_jobs WHERE job_kind='portrait'")
        )[0]
        assert row["status"] == "failed"
        assert row["last_error"] == "Blocked by failed profile derivation"


@pytest.mark.asyncio
async def test_merge_republishes_complete_l1_link_batch(identity):
    from magi.memory.l2.projection.entity_links import _append_ready_governance_batch

    await identity.catalog.upsert_entity(
        entity_id="food:apple", canonical_name="Apple", entity_type="food"
    )
    async with sqlite_connection_async(identity.db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        await _append_ready_governance_batch(
            db,
            batch_key="before",
            desired_links_by_event={
                "e1": [("other:apple", "other", 0.95)],
                "e2": [("unrelated", "topic", 0.9)],
            },
        )
        await db.commit()
    await apply_preview(
        identity,
        EntityChangeCommand(kind="merge", entity_id="other:apple", target_entity_id="food:apple"),
    )
    async with sqlite_connection_async(identity.db_path) as db:
        rows = await query_rows(
            db, "SELECT * FROM l2_event_entity_link_outbox WHERE state='ready' ORDER BY event_id"
        )
        assert len(rows) == 2
        assert rows[0]["batch_key"] == rows[1]["batch_key"]
        assert json.loads(rows[0]["desired_links_json"])[0]["entity_id"] == "food:apple"
        assert json.loads(rows[0]["desired_links_json"])[0]["entity_type"] == "food"
        assert json.loads(rows[1]["desired_links_json"])[0]["entity_id"] == "unrelated"
