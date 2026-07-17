from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    relationship_claim_fingerprint,
    relationship_slot_key,
    relationship_triple_id,
    scope_key,
)
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.maintenance import L2EntityMaintenance, _canonical_entity_id
from magi.memory.l2.graph.identity_rekey import (
    rekey_relationship_identity,
    relationship_slot_key_on_connection,
)
from magi.memory.l2.store import L2CognitionStore


def _migrate_memory_shared_schema(db_path: str) -> None:
    from alembic import command

    from magi.db.runner import MIGRATION_TARGETS, _build_config

    memory_shared_target = next(
        target for target in MIGRATION_TARGETS if target.name == "memory_shared"
    )
    command.upgrade(_build_config(memory_shared_target, Path(db_path)), "head")


async def _init_schema(db_path: str) -> None:
    _migrate_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    catalog = L2EntityCatalog(db_path=db_path)
    await catalog.initialize()


@pytest.mark.asyncio
async def test_relationship_rekey_uses_default_conflict_slots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        store = L2CognitionStore(db_path=db_path)
        await store.initialize()
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            likes_slot = await relationship_slot_key_on_connection(
                db,
                subject_id="user:self",
                predicate="LIKES",
                object_id="food:ramen",
            )
            dislikes_slot = await relationship_slot_key_on_connection(
                db,
                subject_id="user:self",
                predicate="DISLIKES",
                object_id="food:ramen",
            )

        assert likes_slot == store.relationship_slot_key_for(
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen",
        )
        assert dislikes_slot == store.relationship_slot_key_for(
            subject_id="user:self",
            predicate="DISLIKES",
            object_id="food:ramen",
        )
        assert likes_slot == dislikes_slot


@pytest.mark.asyncio
async def test_entity_merge_rekeys_name_evidence_and_preserves_independent_aliases(
    tmp_path: Path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await _init_schema(db_path)
    catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
    await catalog.upsert_entity(
        entity_id="person:winner",
        canonical_name="Winner name",
        entity_type="person",
    )
    await catalog.upsert_entity(
        entity_id="person:loser",
        canonical_name="Source name",
        entity_type="person",
        source_event_ids=["event-source"],
    )
    await catalog.add_alias(
        entity_id="person:loser",
        alias_text="Source alias",
        source_event_ids=["event-source"],
    )
    await catalog.add_alias(
        entity_id="person:loser",
        alias_text="Independent alias",
    )

    maintenance = L2EntityMaintenance(db_path=db_path)
    await maintenance._merge_entity_into("person:winner", "person:loser")

    async with sqlite_connection_async(db_path) as db:
        evidence_rows = await (
            await db.execute(
                """
                SELECT entity_id, event_id
                FROM entity_name_evidence
                ORDER BY name_kind, normalized_name
                """
            )
        ).fetchall()
        assert [tuple(row) for row in evidence_rows] == [
            ("person:winner", "event-source"),
            ("person:winner", "event-source"),
        ]
    store = L2CognitionStore(db_path=db_path)
    await store.forget_source_events(["event-source"], reason="user_delete_event")

    entity = (await catalog.list_entities(limit=10))[0]
    assert entity["entity_id"] == "person:winner"
    assert entity["canonical_name"] == "Winner name"
    assert entity["aliases"] == ["Independent alias"]


@pytest.mark.asyncio
async def test_relationship_rekey_preserves_conflict_effect_ownership(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    victim_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="DISLIKES",
        object_id="food:ramen-alias",
        object_type="food",
        evidence_event_ids=["evt-dislike-alias"],
        confidence=0.8,
        observed_at=time.time() - 60,
        source_type="chat",
    )
    target_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="food:udon",
        object_type="food",
        evidence_event_ids=["evt-like-udon"],
        confidence=0.8,
        observed_at=time.time() - 30,
        source_type="chat",
    )
    corrected = await store.apply_relationship_correction(
        triple_id=target_id,
        request_id="correct-to-ramen-alias",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "food:ramen-alias", "object_type": "food"},
    )
    assert corrected is not None
    replacement_id = corrected["current_relationship"]["triple_id"]

    async with sqlite_connection_async(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        victim_rekey = await rekey_relationship_identity(
            db,
            source_triple_id=victim_id,
            subject_id="user:u1",
            predicate="DISLIKES",
            object_id="food:ramen-canonical",
            now=time.time(),
        )
        replacement_rekey = await rekey_relationship_identity(
            db,
            source_triple_id=replacement_id,
            subject_id="user:u1",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            now=time.time(),
        )
        await db.commit()

    assert victim_rekey.triple_id is not None
    assert replacement_rekey.triple_id is not None
    async with sqlite_connection_async(store.db_path) as db:
        async with db.execute(
            """
            SELECT victim_triple_id, replacement_triple_id
            FROM memory_relationship_conflict_effects
            WHERE correction_id = ?
            """,
            (corrected["correction"]["correction_id"],),
        ) as cursor:
            effect = await cursor.fetchone()
    assert effect is not None
    assert effect[0] == victim_rekey.triple_id
    assert effect[1] == replacement_rekey.triple_id

    reverted = await store.revert_relationship_correction(
        correction_id=corrected["correction"]["correction_id"],
        request_id="revert-ramen-alias-correction",
        actor_id="user:u1",
    )
    assert reverted is not None
    restored = await store.get_relationship(triple_id=victim_rekey.triple_id)
    assert restored is not None
    assert restored["status"] == "active"
    assert restored["deprecated_by"] is None


@pytest.mark.asyncio
async def test_ghost_object_id_rewrites_to_catalog_entity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="software:twitter-handle",
            canonical_name="X",
            entity_type="software",
        )
        ghost_object = _canonical_entity_id("software", "X")
        assert ghost_object == "software:x"
        now = time.time()
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "triple_test_ghost",
                    "user:self",
                    "user",
                    "USES",
                    ghost_object,
                    "software",
                    0.9,
                    json.dumps(["e1"]),
                    1,
                    now,
                    now,
                    now,
                    now,
                    "active",
                ),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(min_mentions_to_keep=99, merge_fragments=False, prune_orphans=False)
        assert stats.ghost_edges_rewritten >= 1

        async with sqlite_connection_async(db_path) as db:
            rewritten_triple_id = relationship_triple_id(
                subject_id="user:self",
                predicate="USES",
                object_id="software:twitter-handle",
            )
            async with db.execute(
                "SELECT object_id FROM knowledge_graph WHERE triple_id = ?",
                (rewritten_triple_id,),
            ) as cur:
                row = await cur.fetchone()
        assert row is not None
        assert row[0] == "software:twitter-handle"


@pytest.mark.asyncio
async def test_ghost_rewrite_rekeys_relationship_governance_references() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="food:ramen-canonical",
            canonical_name="Ramen",
            entity_type="food",
        )
        ghost_id = _canonical_entity_id("food", "Ramen")
        project_scope = {
            "all_of": [
                {
                    "dimension": "project",
                    "context_id": f"ctx_project_{'a' * 64}",
                }
            ]
        }
        store = L2CognitionStore(db_path=db_path)
        old_triple_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id=ghost_id,
            object_type="food",
            evidence_event_ids=["evt-ghost"],
            confidence=0.8,
            observed_at=time.time(),
            source_type="chat",
            scope=project_scope,
        )
        corrected = await store.apply_relationship_correction(
            triple_id=old_triple_id,
            request_id="correct-ghost-relationship",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": "food:soba", "object_type": "food"},
        )
        assert corrected is not None
        correction_id = corrected["correction"]["correction_id"]
        scope_key_value = scope_key(project_scope)
        new_triple_id = relationship_triple_id(
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            scope_key_value=scope_key_value,
        )
        new_slot_key = store.relationship_slot_key_for(
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
        )
        new_fingerprint = relationship_claim_fingerprint(
            slot_key_value=new_slot_key,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            scope_key_value=scope_key_value,
        )

        async with sqlite_connection_async(db_path) as db:
            now = time.time()
            await db.execute(
                """
                INSERT INTO memory_derivation_dependencies(
                    artifact_kind, artifact_id, source_kind, source_id,
                    subject_key, source_revision, created_at
                ) VALUES ('snapshot', 'snapshot-user', 'edge', ?, 'user:self', 1, ?)
                """,
                (old_triple_id, now),
            )
            await db.execute(
                """
                INSERT INTO tom_snapshots(
                    snapshot_id, entity_id, entity_type, relationship_topology,
                    active_record_ids, last_updated_at, created_at
                ) VALUES (?, 'user:self', 'user', ?, ?, ?, ?)
                """,
                (
                    "snapshot-user",
                    json.dumps({"edge": f"edge:{old_triple_id}"}),
                    json.dumps([old_triple_id]),
                    now,
                    now,
                ),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            min_mentions_to_keep=99,
            merge_fragments=False,
            prune_orphans=False,
            clean_stale_snapshots=False,
        )
        assert stats.ghost_edges_rewritten >= 1

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            edge = await (
                await db.execute(
                    "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                    (new_triple_id,),
                )
            ).fetchone()
            correction = await (
                await db.execute(
                    "SELECT * FROM memory_corrections WHERE correction_id = ?",
                    (correction_id,),
                )
            ).fetchone()
            version_rows = await (
                await db.execute(
                    "SELECT * FROM knowledge_graph_versions WHERE triple_id = ?",
                    (new_triple_id,),
                )
            ).fetchall()
            dependency = await (
                await db.execute(
                    "SELECT source_id FROM memory_derivation_dependencies "
                    "WHERE artifact_id = 'snapshot-user'"
                )
            ).fetchone()
            snapshot = await (
                await db.execute(
                    "SELECT relationship_topology, active_record_ids "
                    "FROM tom_snapshots WHERE snapshot_id = 'snapshot-user'"
                )
            ).fetchone()
            old_refs = await (
                await db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM knowledge_graph WHERE triple_id = ?) +
                        (SELECT COUNT(*) FROM knowledge_graph_versions WHERE triple_id = ?) +
                        (SELECT COUNT(*) FROM memory_derivation_dependencies
                         WHERE source_kind = 'edge' AND source_id = ?)
                    """,
                    (old_triple_id, old_triple_id, old_triple_id),
                )
            ).fetchone()

        assert edge is not None
        assert edge["object_id"] == "food:ramen-canonical"
        assert edge["slot_key"] == new_slot_key
        assert edge["claim_fingerprint"] == new_fingerprint
        assert correction is not None
        assert correction["target_id"] == new_triple_id
        assert correction["slot_key"] == new_slot_key
        assert correction["claim_fingerprint"] == new_fingerprint
        before = json.loads(correction["before_json"])
        assert before["triple_id"] == new_triple_id
        assert before["object_id"] == "food:ramen-canonical"
        assert before["slot_key"] == new_slot_key
        assert before["claim_fingerprint"] == new_fingerprint
        assert version_rows
        assert all(row["object_id"] == "food:ramen-canonical" for row in version_rows)
        assert all(row["slot_key"] == new_slot_key for row in version_rows)
        assert all(row["claim_fingerprint"] == new_fingerprint for row in version_rows)
        assert dependency["source_id"] == new_triple_id
        assert json.loads(snapshot["relationship_topology"])["edge"] == f"edge:{new_triple_id}"
        assert json.loads(snapshot["active_record_ids"]) == [new_triple_id]
        assert old_refs[0] == 0

        reverted = await store.revert_relationship_correction(
            correction_id=correction_id,
            request_id="revert-correct-ghost-relationship",
            actor_id="user:self",
        )
        assert reverted is not None
        assert reverted["current_relationship"]["triple_id"] == new_triple_id
        assert reverted["current_relationship"]["object_id"] == "food:ramen-canonical"


@pytest.mark.asyncio
async def test_ghost_rewrite_collision_keeps_authoritative_correction_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="food:ramen-canonical",
            canonical_name="Ramen",
            entity_type="food",
        )
        ghost_id = _canonical_entity_id("food", "Ramen")
        store = L2CognitionStore(db_path=db_path)
        original_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:udon",
            object_type="food",
            evidence_event_ids=["evt-udon"],
            confidence=0.7,
            observed_at=time.time(),
            source_type="chat",
        )
        corrected = await store.apply_relationship_correction(
            triple_id=original_id,
            request_id="correct-to-ghost-ramen",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": ghost_id, "object_type": "food"},
        )
        assert corrected is not None
        ghost_triple_id = corrected["current_relationship"]["triple_id"]
        correction_id = corrected["correction"]["correction_id"]
        canonical_triple_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            object_type="food",
            evidence_event_ids=["evt-canonical"],
            confidence=0.6,
            observed_at=time.time(),
            source_type="sensor",
        )

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            min_mentions_to_keep=99,
            merge_fragments=False,
            prune_orphans=False,
        )
        assert stats.ghost_rows_merged == 1

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            current = await (
                await db.execute(
                    "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                    (canonical_triple_id,),
                )
            ).fetchone()
            duplicates = await (await db.execute("""
                    SELECT COUNT(*) FROM knowledge_graph
                    WHERE subject_id = 'user:self' AND predicate = 'LIKES'
                      AND object_id = 'food:ramen-canonical' AND scope_key = 'global'
                    """)).fetchone()
            correction = await (
                await db.execute(
                    "SELECT * FROM memory_corrections WHERE correction_id = ?",
                    (correction_id,),
                )
            ).fetchone()
            versions = await (
                await db.execute(
                    "SELECT * FROM knowledge_graph_versions WHERE triple_id = ?",
                    (canonical_triple_id,),
                )
            ).fetchall()
            stale_versions = await (
                await db.execute(
                    "SELECT COUNT(*) FROM knowledge_graph_versions WHERE triple_id = ?",
                    (ghost_triple_id,),
                )
            ).fetchone()

        assert current is not None
        assert current["authority_ref"] == f"correction:{correction_id}"
        assert current["status"] == "active"
        assert set(json.loads(current["evidence_event_ids"])) == {"evt-canonical"}
        assert duplicates[0] == 1
        assert correction["replacement_target_id"] == canonical_triple_id
        replacement = json.loads(correction["replacement_json"])
        assert replacement["triple_id"] == canonical_triple_id
        assert replacement["object_id"] == "food:ramen-canonical"
        assert len(versions) >= 2
        assert stale_versions[0] == 0

        reverted = await store.revert_relationship_correction(
            correction_id=correction_id,
            request_id="revert-correct-to-ghost-ramen",
            actor_id="user:self",
        )
        assert reverted is not None
        assert reverted["current_relationship"]["triple_id"] == original_id


@pytest.mark.asyncio
async def test_forgotten_relationship_stays_forgotten_after_identity_merge() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="food:ramen-canonical",
            canonical_name="Ramen",
            entity_type="food",
        )
        ghost_id = _canonical_entity_id("food", "Ramen")
        store = L2CognitionStore(db_path=db_path)
        observed_at = time.time() - 60
        ghost_triple_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id=ghost_id,
            object_type="food",
            evidence_event_ids=["evt-ghost-forgotten"],
            confidence=0.8,
            observed_at=observed_at,
            source_type="chat",
        )
        canonical_triple_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            object_type="food",
            evidence_event_ids=["evt-canonical-existing"],
            confidence=0.7,
            observed_at=observed_at + 1,
            source_type="sensor",
        )
        async with sqlite_connection_async(db_path) as db:
            old_fingerprint = str(
                (
                    await (
                        await db.execute(
                            "SELECT claim_fingerprint FROM knowledge_graph WHERE triple_id = ?",
                            (ghost_triple_id,),
                        )
                    ).fetchone()
                )[0]
            )

        await store.forget_entity(entity_id=ghost_id)
        await store.forget_entity(entity_id="food:ramen-canonical")
        stats = await L2EntityMaintenance(db_path=db_path).run(
            min_mentions_to_keep=99,
            merge_fragments=False,
            prune_orphans=False,
            clean_stale_snapshots=False,
        )
        assert stats.ghost_rows_merged == 1

        new_slot = store.relationship_slot_key_for(
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
        )
        new_fingerprint = relationship_claim_fingerprint(
            slot_key_value=new_slot,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
        )
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            await rekey_relationship_identity(
                db,
                source_triple_id=canonical_triple_id,
                subject_id="user:self",
                predicate="LIKES",
                object_id="food:ramen-canonical",
                now=time.time(),
            )
            await db.commit()
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            current = await (
                await db.execute(
                    "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                    (canonical_triple_id,),
                )
            ).fetchone()
            rule = await (
                await db.execute(
                    """
                    SELECT * FROM memory_forget_claim_rules
                    WHERE target_kind = 'edge' AND claim_fingerprint = ?
                    """,
                    (new_fingerprint,),
                )
            ).fetchone()
            rule_count = await (
                await db.execute(
                    """
                    SELECT COUNT(*) FROM memory_forget_claim_rules
                    WHERE target_kind = 'edge' AND claim_fingerprint = ?
                    """,
                    (new_fingerprint,),
                )
            ).fetchone()
            stale_governance = await (
                await db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM memory_forget_claim_rules
                         WHERE target_kind = 'edge' AND claim_fingerprint = ?) +
                        (SELECT COUNT(*) FROM memory_claim_evidence_events
                         WHERE target_kind = 'edge' AND claim_fingerprint = ?)
                    """,
                    (old_fingerprint, old_fingerprint),
                )
            ).fetchone()
            version_ids = await (
                await db.execute("SELECT DISTINCT triple_id FROM knowledge_graph_versions")
            ).fetchall()
            ledger_events = await (
                await db.execute(
                    """
                    SELECT event_id FROM memory_claim_evidence_events
                    WHERE target_kind = 'edge' AND claim_fingerprint = ?
                    ORDER BY event_id
                    """,
                    (new_fingerprint,),
                )
            ).fetchall()

        assert current is not None
        assert current["status"] == "archived"
        assert current["status_reason"] == "user_forget"
        assert current["claim_fingerprint"] == new_fingerprint
        assert json.loads(current["evidence_event_ids"]) == []
        assert rule is not None
        assert rule_count[0] == 1
        assert rule["semantic_fingerprint"] == new_fingerprint
        assert stale_governance[0] == 0
        assert {row[0] for row in version_ids} == {canonical_triple_id}
        assert {row[0] for row in ledger_events} == {
            "evt-canonical-existing",
            "evt-ghost-forgotten",
        }

        replayed_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            object_type="food",
            evidence_event_ids=["evt-ghost-forgotten"],
            confidence=0.9,
            observed_at=time.time(),
            source_type="chat",
        )
        assert replayed_id == canonical_triple_id
        replayed = await store.get_relationship(triple_id=canonical_triple_id)
        assert replayed is not None
        assert replayed["status"] == "archived"


@pytest.mark.asyncio
async def test_relationship_merge_does_not_copy_forgotten_evidence_to_active_winner() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="food:ramen-canonical",
            canonical_name="Ramen",
            entity_type="food",
        )
        ghost_id = _canonical_entity_id("food", "Ramen")
        store = L2CognitionStore(db_path=db_path)
        ghost_triple_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id=ghost_id,
            object_type="food",
            evidence_event_ids=["evt-forgotten-ghost-ramen"],
            confidence=0.8,
            observed_at=time.time() - 60,
            source_type="chat",
        )
        original_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:udon",
            object_type="food",
            evidence_event_ids=["evt-original-udon"],
            confidence=0.7,
            observed_at=time.time() - 30,
            source_type="chat",
        )
        corrected = await store.apply_relationship_correction(
            triple_id=original_id,
            request_id="correct-udon-to-canonical-ramen",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": "food:ramen-canonical", "object_type": "food"},
            source_event_id="evt-canonical-ramen-correction",
        )
        assert corrected is not None
        canonical_triple_id = corrected["current_relationship"]["triple_id"]

        await store.forget_entity(entity_id=ghost_id)
        forgotten = await store.get_relationship(triple_id=ghost_triple_id)
        assert forgotten is not None
        assert forgotten["status"] == "archived"

        stats = await L2EntityMaintenance(db_path=db_path).run(
            min_mentions_to_keep=99,
            merge_fragments=False,
            prune_orphans=False,
            clean_stale_snapshots=False,
        )
        assert stats.ghost_rows_merged == 1

        current = await store.get_relationship(triple_id=canonical_triple_id)
        assert current is not None
        assert current["status"] == "active"
        assert current["authority_ref"].startswith("correction:")
        assert "evt-forgotten-ghost-ramen" not in current["evidence_event_ids"]
        assert "evt-canonical-ramen-correction" in current["evidence_event_ids"]
        assert current["observation_count"] == 1
        assert current["confidence"] == 0.95


@pytest.mark.asyncio
async def test_forgotten_relationship_correction_rekeys_to_canonical_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="food:ramen-canonical",
            canonical_name="Ramen",
            entity_type="food",
        )
        ghost_id = _canonical_entity_id("food", "Ramen")
        store = L2CognitionStore(db_path=db_path)
        original_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:udon",
            object_type="food",
            evidence_event_ids=["evt-original-udon"],
            confidence=0.8,
            observed_at=time.time() - 60,
            source_type="chat",
        )
        corrected = await store.apply_relationship_correction(
            triple_id=original_id,
            request_id="correct-to-forgotten-ghost",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": ghost_id, "object_type": "food"},
        )
        assert corrected is not None
        correction_id = corrected["correction"]["correction_id"]
        ghost_replacement_id = corrected["current_relationship"]["triple_id"]
        old_fingerprint = corrected["current_relationship"]["claim_fingerprint"]

        await store.forget_entity(entity_id=ghost_id)
        stats = await L2EntityMaintenance(db_path=db_path).run(
            min_mentions_to_keep=99,
            merge_fragments=False,
            prune_orphans=False,
            clean_stale_snapshots=False,
        )
        assert stats.ghost_edges_rewritten >= 1

        canonical_id = relationship_triple_id(
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
        )
        new_slot = store.relationship_slot_key_for(
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
        )
        new_fingerprint = relationship_claim_fingerprint(
            slot_key_value=new_slot,
            subject_id="user:self",
            predicate="LIKES",
            object_id="food:ramen-canonical",
        )
        history = await store.get_relationship_correction_history(triple_id=canonical_id)
        assert [row["correction_id"] for row in history["corrections"]] == [correction_id]

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            correction = await (
                await db.execute(
                    "SELECT * FROM memory_corrections WHERE correction_id = ?",
                    (correction_id,),
                )
            ).fetchone()
            replacement_rule = await (
                await db.execute(
                    """
                    SELECT * FROM memory_correction_rules
                    WHERE correction_id = ? AND claim_fingerprint = ?
                    """,
                    (correction_id, new_fingerprint),
                )
            ).fetchone()
            forget_rule = await (
                await db.execute(
                    """
                    SELECT * FROM memory_forget_claim_rules
                    WHERE target_kind = 'edge' AND claim_fingerprint = ?
                    """,
                    (new_fingerprint,),
                )
            ).fetchone()
            stale_refs = await (
                await db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM knowledge_graph
                         WHERE triple_id = ?) +
                        (SELECT COUNT(*) FROM knowledge_graph_versions
                         WHERE triple_id = ?) +
                        (SELECT COUNT(*) FROM memory_forget_claim_rules
                         WHERE target_kind = 'edge' AND claim_fingerprint = ?) +
                        (SELECT COUNT(*) FROM memory_claim_evidence_events
                         WHERE target_kind = 'edge' AND claim_fingerprint = ?)
                    """,
                    (
                        ghost_replacement_id,
                        ghost_replacement_id,
                        old_fingerprint,
                        old_fingerprint,
                    ),
                )
            ).fetchone()
        assert correction is not None
        assert correction["replacement_target_id"] == canonical_id
        replacement = json.loads(correction["replacement_json"])
        assert replacement["triple_id"] == canonical_id
        assert replacement["object_id"] == "food:ramen-canonical"
        assert replacement["slot_key"] == new_slot
        assert replacement["claim_fingerprint"] == new_fingerprint
        assert replacement_rule is not None
        assert replacement_rule["rule_kind"] == "block_claim"
        assert replacement_rule["slot_key"] == new_slot
        assert forget_rule is not None
        assert forget_rule["semantic_fingerprint"] == new_fingerprint
        assert stale_refs[0] == 0

        replayed_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen-canonical",
            object_type="food",
            evidence_event_ids=["evt-replayed-canonical-ramen"],
            confidence=0.9,
            observed_at=time.time(),
            source_type="chat",
        )
        assert replayed_id == canonical_id
        replayed = await store.get_relationship(triple_id=canonical_id)
        assert replayed is not None
        assert replayed["status"] == "archived"


@pytest.mark.asyncio
async def test_predicate_consolidation_rekeys_correction_replacement() -> None:
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        store = L2CognitionStore(db_path=db_path)
        original_id = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="ADORES",
            object_id="topic:old",
            object_type="topic",
            evidence_event_ids=["evt-old"],
            confidence=0.7,
            observed_at=time.time(),
            source_type="chat",
        )
        corrected = await store.apply_relationship_correction(
            triple_id=original_id,
            request_id="correct-open-predicate-object",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement={"object_id": "topic:ml", "object_type": "topic"},
        )
        assert corrected is not None
        open_replacement_id = corrected["current_relationship"]["triple_id"]
        correction_id = corrected["correction"]["correction_id"]

        from magi.memory.l2.ontology import get_predicate_synonym_group

        def synonym_group(predicate: str) -> str | None:
            if predicate.strip().upper() == "ADORES":
                return "affinity"
            return get_predicate_synonym_group(predicate)

        with patch(
            "magi.memory.l2.entities.maintenance.get_predicate_synonym_group",
            side_effect=synonym_group,
        ):
            stats = await L2EntityMaintenance(db_path=db_path).run(
                resolve_ghosts=False,
                merge_fragments=False,
                prune_orphans=False,
                expire_future_intents=False,
                expire_decayed_assertions=False,
                clean_stale_snapshots=False,
                reconcile_stale=False,
            )
        assert stats.open_predicates_consolidated == 1

        new_predicate = "INTERESTED_IN"
        new_triple_id = relationship_triple_id(
            subject_id="user:self",
            predicate=new_predicate,
            object_id="topic:ml",
        )
        new_slot_key = relationship_slot_key(
            subject_id="user:self",
            predicate=new_predicate,
            object_id="topic:ml",
        )
        new_fingerprint = relationship_claim_fingerprint(
            slot_key_value=new_slot_key,
            subject_id="user:self",
            predicate=new_predicate,
            object_id="topic:ml",
        )
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            edge = await (
                await db.execute(
                    "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                    (new_triple_id,),
                )
            ).fetchone()
            correction = await (
                await db.execute(
                    "SELECT * FROM memory_corrections WHERE correction_id = ?",
                    (correction_id,),
                )
            ).fetchone()
            rule = await (
                await db.execute(
                    """
                    SELECT * FROM memory_correction_rules
                    WHERE correction_id = ? AND rule_kind = 'authoritative_slot'
                    """,
                    (correction_id,),
                )
            ).fetchone()
            stale_refs = await (
                await db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM knowledge_graph WHERE triple_id = ?) +
                        (SELECT COUNT(*) FROM knowledge_graph_versions WHERE triple_id = ?)
                    """,
                    (open_replacement_id, open_replacement_id),
                )
            ).fetchone()

        assert edge is not None
        assert edge["predicate"] == new_predicate
        assert edge["slot_key"] == new_slot_key
        assert edge["claim_fingerprint"] == new_fingerprint
        assert correction["replacement_target_id"] == new_triple_id
        replacement = json.loads(correction["replacement_json"])
        assert replacement["triple_id"] == new_triple_id
        assert replacement["predicate"] == new_predicate
        assert replacement["slot_key"] == new_slot_key
        assert replacement["claim_fingerprint"] == new_fingerprint
        assert rule["slot_key"] == new_slot_key
        assert rule["claim_fingerprint"] == new_fingerprint
        assert stale_refs[0] == 0

        reverted = await store.revert_relationship_correction(
            correction_id=correction_id,
            request_id="revert-correct-open-predicate-object",
            actor_id="user:self",
        )
        assert reverted is not None
        assert reverted["current_relationship"]["triple_id"] == original_id


@pytest.mark.asyncio
async def test_ghost_object_id_rewrites_by_evidence_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="media:1ee3b9131dd8",
            canonical_name="归潮",
            entity_type="media",
        )
        now = time.time()
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status,
                    evidence_text, natural_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "triple_guichao_ghost",
                    "user:self",
                    "user",
                    "LISTENED",
                    "media:guichao-caimingxi",
                    "media",
                    1.0,
                    json.dumps(["evt-guichao"]),
                    1,
                    now,
                    now,
                    now,
                    now,
                    "active",
                    "在网易云音乐听了蔡明希（不才）的《归潮》...播放了4分钟",
                    "user:self LISTENED media:guichao-caimingxi",
                ),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(min_mentions_to_keep=99, merge_fragments=False, prune_orphans=False)
        assert stats.ghost_edges_rewritten >= 1

        async with sqlite_connection_async(db_path) as db:
            rewritten_triple_id = relationship_triple_id(
                subject_id="user:self",
                predicate="LISTENED",
                object_id="media:1ee3b9131dd8",
            )
            async with db.execute(
                "SELECT object_id FROM knowledge_graph WHERE triple_id = ?",
                (rewritten_triple_id,),
            ) as cur:
                row = await cur.fetchone()
        assert row is not None
        assert row[0] == "media:1ee3b9131dd8"


@pytest.mark.asyncio
async def test_merge_same_name_mergeable_types() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        now = time.time()
        await catalog.upsert_entity(
            entity_id="software:claude-app",
            canonical_name="Claude",
            entity_type="software",
        )
        await catalog.upsert_entity(
            entity_id="technology:claude-ai",
            canonical_name="Claude",
            entity_type="technology",
        )
        await catalog.upsert_entity(
            entity_id="product:claude-assistant",
            canonical_name="Claude",
            entity_type="product",
        )
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                INSERT INTO entity_mentions(
                    mention_text, normalized_surface, entity_type, evidence_event_ids,
                    evidence_text, resolved_entity_id, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Claude", "claude", "software", "[]", "x", "software:claude-app", 0.95, now),
            )
            await db.execute(
                """
                INSERT INTO entity_mentions(
                    mention_text, normalized_surface, entity_type, evidence_event_ids,
                    evidence_text, resolved_entity_id, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Claude", "claude", "technology", "[]", "x", "technology:claude-ai", 0.9, now),
            )
            await db.execute(
                """
                INSERT INTO entity_mentions(
                    mention_text, normalized_surface, entity_type, evidence_event_ids,
                    evidence_text, resolved_entity_id, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Claude app",
                    "claude-app",
                    "software",
                    "[]",
                    "x",
                    "software:claude-app",
                    0.95,
                    now + 0.1,
                ),
            )
            await db.commit()

        store = L2CognitionStore(db_path=db_path)
        assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": "technology:claude-ai",
                "entity_type": "technology",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "focused",
                "confidence_score": 0.8,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "evidence_events": ["evt-claude-focused"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )
        assert (
            await store.refresh_entity_snapshot(
                entity_id="technology:claude-ai",
                entity_type="technology",
            )
            is not None
        )

        maint = L2EntityMaintenance(db_path=db_path, cognition_store=store)
        stats = await maint.run(
            min_mentions_to_keep=99,
            resolve_ghosts=False,
            prune_orphans=False,
        )
        assert stats.fragment_entities_merged == 2
        assert stats.snapshots_refreshed == 1

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT entity_id FROM entity_catalog
                WHERE LOWER(TRIM(canonical_name)) = ?
                """,
                ("claude",),
            ) as cur:
                entities = await cur.fetchall()
            snapshot = await (await db.execute("""
                    SELECT entity_id, current_mood, update_source_assertion_ids
                    FROM tom_snapshots
                    WHERE entity_id IN ('software:claude-app', 'technology:claude-ai')
                    """)).fetchone()
        assert [row["entity_id"] for row in entities] == ["software:claude-app"]
        assert snapshot is not None
        assert snapshot["entity_id"] == "software:claude-app"
        assert snapshot["current_mood"] == "focused"
        assert json.loads(snapshot["update_source_assertion_ids"]) == [assertion_id]


@pytest.mark.asyncio
async def test_fragment_merge_rekeys_forgotten_assertion_governance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        winner_id = "software:alice-primary"
        loser_id = "technology:alice-fragment"
        for entity_id, entity_type in (
            (winner_id, "software"),
            (loser_id, "technology"),
        ):
            await catalog.upsert_entity(
                entity_id=entity_id,
                canonical_name="Alice",
                entity_type=entity_type,
            )
        now = time.time()
        async with sqlite_connection_async(db_path) as db:
            await db.executemany(
                """
                INSERT INTO entity_mentions(
                    mention_text, normalized_surface, entity_type,
                    evidence_event_ids, evidence_text, resolved_entity_id,
                    confidence, created_at
                ) VALUES (?, ?, ?, '[]', 'Alice', ?, 0.9, ?)
                """,
                [
                    ("Alice", "alice-primary-1", "software", winner_id, now),
                    ("Alice", "alice-primary-2", "software", winner_id, now + 0.1),
                    ("Alice", "alice-fragment", "technology", loser_id, now + 0.2),
                ],
            )
            await db.commit()

        store = L2CognitionStore(db_path=db_path)
        assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": loser_id,
                "entity_type": "technology",
                "trait_family": "preference_profile",
                "trait_name": "food.preference",
                "trait_value": "ramen",
                "confidence_score": 0.8,
                "evidence_events": ["evt-fragment-ramen"],
                "volatility_index": 0.2,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "validation_state": "corroborated",
                "first_inferred_at": now,
                "last_validated_at": now,
                "temporal_scope": "persistent",
            }
        )
        await store.forget_entity(entity_id=loser_id)
        stats = await L2EntityMaintenance(db_path=db_path).run(
            resolve_ghosts=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            clean_stale_snapshots=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.fragment_entities_merged == 1

        new_slot = assertion_slot_key(
            entity_type="software",
            entity_id=winner_id,
            trait_name="food.preference",
        )
        new_fingerprint = assertion_claim_fingerprint(
            slot_key_value=new_slot,
            trait_value="ramen",
        )
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            assertion = await (
                await db.execute(
                    "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                    (assertion_id,),
                )
            ).fetchone()
            rule = await (
                await db.execute(
                    """
                    SELECT * FROM memory_forget_claim_rules
                    WHERE target_kind = 'assertion' AND claim_fingerprint = ?
                    """,
                    (new_fingerprint,),
                )
            ).fetchone()
        assert assertion is not None
        assert assertion["entity_id"] == winner_id
        assert assertion["entity_type"] == "software"
        assert assertion["slot_key"] == new_slot
        assert assertion["claim_fingerprint"] == new_fingerprint
        assert assertion["status"] == "archived"
        assert rule is not None
        assert rule["semantic_fingerprint"] == new_fingerprint

        replayed = await store.upsert_assertion_candidate(
            {
                "entity_id": winner_id,
                "entity_type": "software",
                "trait_family": "preference_profile",
                "trait_name": "food.preference",
                "trait_value": "ramen",
                "confidence_score": 0.9,
                "evidence_events": ["evt-fragment-ramen"],
                "volatility_index": 0.2,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "validation_state": "corroborated",
                "first_inferred_at": time.time(),
                "last_validated_at": time.time(),
                "temporal_scope": "persistent",
            }
        )
        assert replayed.startswith("blocked:")
        assert await store.list_current_assertions(entity_id=winner_id) == []


@pytest.mark.asyncio
async def test_prune_orphan_single_mention_no_graph() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="person:nobody",
            canonical_name="Nobody",
            entity_type="person",
            source_event_ids=["event-nobody"],
        )
        now = time.time()
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                INSERT INTO entity_mentions(
                    mention_text, normalized_surface, entity_type, evidence_event_ids,
                    evidence_text, resolved_entity_id, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Nobody",
                    "nobody",
                    "person",
                    '["event-nobody"]',
                    "x",
                    "person:nobody",
                    0.9,
                    now,
                ),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            min_mentions_to_keep=2,
            resolve_ghosts=False,
            merge_fragments=False,
        )
        assert stats.orphans_pruned >= 1
        async with sqlite_connection_async(db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM entity_catalog WHERE entity_id = ?", ("person:nobody",)
            ) as cur:
                assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_prune_orphan_preserves_independent_entity_name(tmp_path: Path) -> None:
    db_path = str(tmp_path / "memory.db")
    await _init_schema(db_path)
    catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
    await catalog.upsert_entity(
        entity_id="person:manual",
        canonical_name="Manual person",
        entity_type="person",
    )
    await catalog.add_alias(
        entity_id="person:manual",
        alias_text="Manual nickname",
    )

    stats = await L2EntityMaintenance(db_path=db_path).run(
        min_mentions_to_keep=2,
        resolve_ghosts=False,
        merge_fragments=False,
    )

    assert stats.orphans_pruned == 0
    entity = (await catalog.list_entities(limit=10))[0]
    assert entity["canonical_name"] == "Manual person"
    assert entity["aliases"] == ["Manual nickname"]


@pytest.mark.asyncio
async def test_expire_stale_future_intents():
    """Expired future_intent edges should be marked as 'expired' by maintenance."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "l2.db")
        await _init_schema(db_path)

        now = time.time()
        past_expires = now - 100  # expired 100 seconds ago
        future_expires = now + 86400  # expires tomorrow

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        # Insert an edge that has already expired
        tid_expired = await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="user",
            predicate="PLANS_TO",
            object_id="activity:travel",
            object_type="activity",
            fact_kind="future_intent",
            evidence_event_ids=["evt-1"],
            confidence=0.8,
            observed_at=now - 86400 * 31,
            source_type="chat",
            expires_at=past_expires,
        )

        # Insert an edge that hasn't expired yet
        tid_active = await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="user",
            predicate="PLANS_TO",
            object_id="activity:concert",
            object_type="activity",
            fact_kind="future_intent",
            evidence_event_ids=["evt-2"],
            confidence=0.8,
            observed_at=now - 100,
            source_type="chat",
            expires_at=future_expires,
        )

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
        )

        assert stats.expired_future_intents == 1

        edge_expired = await store.get_relationship(triple_id=tid_expired)
        assert edge_expired is not None
        assert edge_expired["status"] == "expired"

        edge_active = await store.get_relationship(triple_id=tid_active)
        assert edge_active is not None
        assert edge_active["status"] == "active"


@pytest.mark.asyncio
async def test_consolidate_open_predicates_rewrites_to_core() -> None:
    """A non-core predicate not in any synonym group is left alone."""

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        now = time.time()

        tid_open = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="STUDYING",
            object_id="topic:ml",
            object_type="topic",
            evidence_event_ids=["evt-open-1"],
            confidence=0.7,
            observed_at=now,
            source_type="chat",
        )

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
        )

        # STUDYING is not in any synonym group, so it should be left alone
        assert stats.open_predicates_consolidated == 0

        edge = await store.get_relationship(triple_id=tid_open)
        assert edge is not None
        assert edge["predicate"] == "STUDYING"


@pytest.mark.asyncio
async def test_maintenance_leaves_pending_edges_when_no_embedding_service() -> None:
    """Maintenance without embedding_service must leave pending edges untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen",
            object_type="food",
            evidence_event_ids=["evt-emb-1"],
            confidence=0.5,
            observed_at=time.time(),
            source_type="chat",
        )

        maint = L2EntityMaintenance(db_path=db_path)
        await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
        )

        # Verify edge still has pending status — maintenance must not embed.
        edges = await store.get_pending_edge_embeddings(limit=10)
        assert len(edges) == 1
        assert edges[0]["embedding_status"] == "pending"


@pytest.mark.asyncio
async def test_maintenance_leaves_pending_edges_even_with_embedding_service() -> None:
    """Maintenance wired with embedding infra must still leave pending edges untouched.

    EdgeEmbeddingDrainer is now the sole embedder; maintenance.run() must not call
    the pipeline regardless of whether embedding_service / edge_vector_index are set.
    """
    from unittest.mock import AsyncMock, MagicMock

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen",
            object_type="food",
            evidence_event_ids=["evt-emb-2"],
            confidence=0.5,
            observed_at=time.time(),
            source_type="chat",
            evidence_text="I really like ramen",
        )

        mock_embedding_service = MagicMock()
        mock_vector_index = MagicMock()
        mock_pipeline_cls = AsyncMock()
        mock_pipeline_cls.upsert_items = AsyncMock(return_value=[])

        maint = L2EntityMaintenance(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        import magi.memory.l2.entities.maintenance as em_module

        original_pipeline = em_module.MemoryEmbeddingPipeline
        em_module.MemoryEmbeddingPipeline = lambda **kwargs: mock_pipeline_cls

        try:
            await maint.run(
                resolve_ghosts=False,
                merge_fragments=False,
                prune_orphans=False,
                expire_future_intents=False,
                consolidate_open_predicates=False,
            )
        finally:
            em_module.MemoryEmbeddingPipeline = original_pipeline

        # The pipeline is still imported by the maintenance module (used by
        # `_clean_non_active_edge_embeddings`), so we patch it — but maintenance must
        # NOT call it to embed *pending* edges. That work moved to EdgeEmbeddingDrainer (#86).
        mock_pipeline_cls.upsert_items.assert_not_called()

        # Edge must still be pending.
        edges = await store.get_pending_edge_embeddings(limit=10)
        assert len(edges) == 1
        assert edges[0]["embedding_status"] == "pending"


@pytest.mark.asyncio
async def test_expire_decayed_assertions_fast_decay():
    """fast_decay assertions older than FAST_DECAY_TTL should be expired."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "l2.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        now = time.time()
        old_time = now - 5 * 3600  # 5 hours ago (> 4h FAST_DECAY_TTL)

        # Old fast_decay assertion — should be expired
        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "trigger",
                "trait_name": "annoyance",
                "trait_value": "high",
                "confidence_score": 0.25,
                "validation_state": "tentative",
                "temporal_scope": "momentary",
                "decay_policy": "fast_decay",
                "evidence_events": ["evt-1"],
                "volatility_index": 0.7,
                "source_domain": "chat",
                "inference_depth": "defensive_psychology",
                "first_inferred_at": old_time,
                "last_validated_at": old_time,
            }
        )
        # Backdate the updated_at
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET updated_at = ? WHERE entity_id = 'user:u1' AND trait_name = 'annoyance'",
                (old_time,),
            )
            await db.commit()

        # Recent fast_decay assertion — should survive
        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u2",
                "entity_type": "user",
                "trait_family": "trigger",
                "trait_name": "frustration",
                "trait_value": "medium",
                "confidence_score": 0.25,
                "validation_state": "tentative",
                "temporal_scope": "momentary",
                "decay_policy": "fast_decay",
                "evidence_events": ["evt-2"],
                "volatility_index": 0.7,
                "source_domain": "chat",
                "inference_depth": "defensive_psychology",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )
        # This one was updated recently, no need to backdate

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
        )

        assert stats.expired_assertions == 1

        old_assertions = await store.list_tom_assertions(entity_id="user:u1")
        assert old_assertions[0]["validation_state"] == "expired"

        recent_assertions = await store.list_tom_assertions(entity_id="user:u2")
        assert recent_assertions[0]["validation_state"] == "tentative"


@pytest.mark.asyncio
async def test_expire_decayed_assertions_session_decay():
    """session_decay assertions older than SESSION_DECAY_TTL should be expired."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "l2.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        now = time.time()
        old_time = now - 25 * 3600  # 25 hours ago (> 24h SESSION_DECAY_TTL)

        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "happy",
                "confidence_score": 0.25,
                "validation_state": "corroborated",
                "temporal_scope": "session",
                "decay_policy": "session_decay",
                "evidence_events": ["evt-1"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "defensive_psychology",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET updated_at = ? WHERE entity_id = 'user:u1'",
                (old_time,),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
        )

        assert stats.expired_assertions == 1

        assertions = await store.list_tom_assertions(entity_id="user:u1")
        assert assertions[0]["validation_state"] == "expired"


@pytest.mark.asyncio
async def test_expire_decayed_assertions_skips_already_rejected():
    """Assertions already in user_rejected state should not be touched by decay GC."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "l2.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        now = time.time()
        old_time = now - 25 * 3600

        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "sad",
                "confidence_score": 0.10,
                "validation_state": "user_rejected",
                "temporal_scope": "session",
                "decay_policy": "session_decay",
                "evidence_events": ["evt-1"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "defensive_psychology",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET updated_at = ? WHERE entity_id = 'user:u1'",
                (old_time,),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
        )

        assert stats.expired_assertions == 0

        # user_rejected is hidden from default retrieval reads (#134); inspect it
        # explicitly to confirm the decay GC left it untouched.
        assertions = await store.list_tom_assertions(entity_id="user:u1", include_inactive=True)
        assert assertions[0]["validation_state"] == "user_rejected"


# -----------------------------------------------------------------------
# A2: Periodic reconciliation of stale entities
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_stale_entities_promotes_tentative():
    """Stale tentative assertions should be re-reconciled and promoted when eligible."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "l2.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        now = time.time()
        old_time = now - 7200  # 2 hours ago (> 1h RECONCILE_STALE_THRESHOLD)

        # Insert a temporary trait assertion with 1 evidence (tentative).
        # After A1 change, reconciliation should promote it to corroborated.
        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "stress",
                "trait_name": "stress_level",
                "trait_value": "high",
                "confidence_score": 0.25,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "decay_policy": "session_decay",
                "evidence_events": ["evt-1"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": old_time,
                "last_validated_at": old_time,
            }
        )
        # Backdate so maintenance considers this stale
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET updated_at = ? WHERE entity_id = 'user:u1'",
                (old_time,),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path, cognition_store=store)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            consolidate_open_predicates=False,
        )

        assert stats.entities_reconciled == 1
        assert stats.snapshots_refreshed == 1

        assertions = await store.list_tom_assertions(entity_id="user:u1")
        assert assertions[0]["validation_state"] == "corroborated"


@pytest.mark.asyncio
async def test_reconcile_stale_skips_recent_entities():
    """Entities with recently-updated assertions should not be re-reconciled."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "l2.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        now = time.time()

        # Insert a tentative assertion that was just updated (not stale)
        await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "happy",
                "confidence_score": 0.25,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "decay_policy": "session_decay",
                "evidence_events": ["evt-1"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )

        maint = L2EntityMaintenance(db_path=db_path, cognition_store=store)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            consolidate_open_predicates=False,
        )

        # Not stale => should not be reconciled
        assert stats.entities_reconciled == 0
        assert stats.snapshots_refreshed == 0


# -----------------------------------------------------------------------
# Consolidate open predicates: evidence merge on duplicate
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_open_predicates_merges_evidence_on_duplicate():
    """When consolidation creates a duplicate triple, evidence should be merged, not lost."""
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        now = time.time()

        # Insert a core-predicate edge (LIKES)
        tid_core = await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen",
            object_type="food",
            evidence_event_ids=["evt-core-1"],
            confidence=0.8,
            observed_at=now - 100,
            source_type="chat",
        )

        # Insert an open-predicate edge (ADORES) — not in PREDICATE_REGISTRY.
        # We'll patch the synonym group to map it to "affinity" (same group as LIKES).
        async with sqlite_connection_async(db_path) as db:
            import uuid as _uuid

            tid_open = str(_uuid.uuid5(_uuid.NAMESPACE_URL, "user:self:ADORES:food:ramen"))
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid_open,
                    "user:self",
                    "user",
                    "ADORES",
                    "food:ramen",
                    "food",
                    0.6,
                    json.dumps(["evt-open-1", "evt-open-2"]),
                    2,
                    now,
                    now,
                    now,
                    now,
                    "active",
                ),
            )
            await db.commit()

        # Patch synonym group so ADORES maps to "affinity" group (which contains LIKES)
        original_fn = __import__(
            "magi.memory.l2.ontology", fromlist=["get_predicate_synonym_group"]
        ).get_predicate_synonym_group

        def patched_synonym_group(predicate: str) -> str | None:
            if predicate.strip().upper() == "ADORES":
                return "affinity"
            return original_fn(predicate)

        with patch(
            "magi.memory.l2.entities.maintenance.get_predicate_synonym_group",
            side_effect=patched_synonym_group,
        ):
            maint = L2EntityMaintenance(db_path=db_path)
            stats = await maint.run(
                resolve_ghosts=False,
                merge_fragments=False,
                prune_orphans=False,
                expire_future_intents=False,
                expire_decayed_assertions=False,
                reconcile_stale=False,
            )

        assert stats.open_predicates_consolidated == 1

        # The core edge should have merged evidence
        edge = await store.get_relationship(triple_id=tid_core)
        assert edge is not None
        evidence = edge["evidence_event_ids"]  # already deserialized by store
        assert "evt-core-1" in evidence
        assert "evt-open-1" in evidence
        assert float(edge["confidence"]) == 0.8  # max(0.8, 0.6)

        # The open edge should be deleted
        open_edge = await store.get_relationship(triple_id=tid_open)
        assert open_edge is None


# -----------------------------------------------------------------------
# Tom entity ref rewrite: UNIQUE conflict handling
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tom_ghost_rewrite_handles_unique_conflict():
    """Rewriting ghost entity_id in tom_trait_assertions should handle UNIQUE conflicts."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="person:alice-canon",
            canonical_name="Alice",
            entity_type="person",
        )

        ghost_id = _canonical_entity_id("person", "Alice")
        assert ghost_id != "person:alice-canon"

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()
        now = time.time()

        # Insert assertion for the ghost entity (higher confidence)
        ghost_assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": ghost_id,
                "entity_type": "person",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "happy",
                "confidence_score": 0.9,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "decay_policy": "session_decay",
                "evidence_events": ["evt-ghost"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )

        # Insert assertion for the target entity with same trait key (lower confidence)
        target_assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": "person:alice-canon",
                "entity_type": "person",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "sad",
                "confidence_score": 0.3,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "decay_policy": "session_decay",
                "evidence_events": ["evt-target"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )

        assert (
            await store.refresh_entity_snapshot(
                entity_id=ghost_id,
                entity_type="person",
            )
            is not None
        )
        assert (
            await store.refresh_entity_snapshot(
                entity_id="person:alice-canon",
                entity_type="person",
            )
            is not None
        )

        maint = L2EntityMaintenance(db_path=db_path, cognition_store=store)
        stats = await maint.run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )

        assert stats.tom_entity_refs_rewritten >= 1

        # Only one assertion should remain for the canonical entity
        assertions = await store.list_tom_assertions(entity_id="person:alice-canon")
        assert len(assertions) == 1
        # The ghost had higher confidence, so its value should win
        assert assertions[0]["trait_value"] == "happy"
        assert assertions[0]["confidence_score"] == 0.9
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            snapshots = await (
                await db.execute(
                    """
                    SELECT entity_id, current_mood, update_source_assertion_ids
                    FROM tom_snapshots
                    WHERE entity_id IN (?, ?)
                    ORDER BY entity_id
                    """,
                    (ghost_id, "person:alice-canon"),
                )
            ).fetchall()
        assert len(snapshots) == 1
        assert snapshots[0]["entity_id"] == "person:alice-canon"
        assert snapshots[0]["current_mood"] == "happy"
        assert json.loads(snapshots[0]["update_source_assertion_ids"]) == [ghost_assertion_id]
        assert target_assertion_id not in json.loads(snapshots[0]["update_source_assertion_ids"])


@pytest.mark.asyncio
async def test_tom_ghost_rewrite_refreshes_shared_target_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        canonical_id = "person:alice-canon"
        await catalog.upsert_entity(
            entity_id=canonical_id,
            canonical_name="Alice",
            entity_type="person",
        )
        store = L2CognitionStore(db_path=db_path)
        now = time.time()
        for ghost_id, trait_name, trait_value in (
            ("person:alice-ghost-one", "mood", "happy"),
            ("person:alice-ghost-two", "engagement", "high"),
        ):
            await store.upsert_assertion_candidate(
                {
                    "entity_id": ghost_id,
                    "entity_type": "person",
                    "trait_family": "state",
                    "trait_name": trait_name,
                    "trait_value": trait_value,
                    "confidence_score": 0.8,
                    "validation_state": "tentative",
                    "temporal_scope": "session",
                    "evidence_events": [f"evt-{trait_name}"],
                    "volatility_index": 0.5,
                    "source_domain": "chat",
                    "inference_depth": "direct",
                    "first_inferred_at": now,
                    "last_validated_at": now,
                }
            )

        refresh_calls: list[str] = []
        original_refresh = store.refresh_entity_snapshot

        async def tracked_refresh(*, entity_id: str, entity_type: str | None = None):
            refresh_calls.append(entity_id)
            return await original_refresh(entity_id=entity_id, entity_type=entity_type)

        maint = L2EntityMaintenance(db_path=db_path, cognition_store=store)

        async def resolve_ghost(_ghost_id: str) -> str:
            return canonical_id

        monkeypatch.setattr(store, "refresh_entity_snapshot", tracked_refresh)
        monkeypatch.setattr(maint, "_resolve_ghost_to_catalog_id", resolve_ghost)
        stats = await maint.run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            clean_stale_snapshots=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )

        assert stats.tom_entity_refs_rewritten == 2
        assert stats.snapshots_refreshed == 1
        assert refresh_calls == [canonical_id]
        assertions = await store.list_tom_assertions(entity_id=canonical_id)
        assert {item["trait_name"] for item in assertions} == {"mood", "engagement"}


@pytest.mark.asyncio
async def test_tom_ghost_rewrite_keeps_snapshots_hidden_when_rebuild_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        canonical_id = "person:alice-canon"
        await catalog.upsert_entity(
            entity_id=canonical_id,
            canonical_name="Alice",
            entity_type="person",
        )
        ghost_id = _canonical_entity_id("person", "Alice")
        store = L2CognitionStore(db_path=db_path)
        now = time.time()
        for entity_id, trait_name, trait_value, event_id in (
            (ghost_id, "mood", "happy", "evt-ghost-happy"),
            (canonical_id, "engagement", "high", "evt-canonical-engagement"),
        ):
            await store.upsert_assertion_candidate(
                {
                    "entity_id": entity_id,
                    "entity_type": "person",
                    "trait_family": "state",
                    "trait_name": trait_name,
                    "trait_value": trait_value,
                    "confidence_score": 0.8,
                    "validation_state": "tentative",
                    "temporal_scope": "session",
                    "evidence_events": [event_id],
                    "volatility_index": 0.5,
                    "source_domain": "chat",
                    "inference_depth": "direct",
                    "first_inferred_at": now,
                    "last_validated_at": now,
                }
            )
            assert (
                await store.refresh_entity_snapshot(
                    entity_id=entity_id,
                    entity_type="person",
                )
                is not None
            )

        async def fail_snapshot_refresh(*, entity_id: str, entity_type: str | None = None):
            raise RuntimeError(f"snapshot refresh failed for {entity_id}:{entity_type}")

        monkeypatch.setattr(store, "refresh_entity_snapshot", fail_snapshot_refresh)
        stats = await L2EntityMaintenance(
            db_path=db_path,
            cognition_store=store,
        ).run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.tom_entity_refs_rewritten == 1
        assert any("refresh snapshot" in error for error in stats.errors)

        async with sqlite_connection_async(db_path) as db:
            snapshot_count = await (
                await db.execute(
                    """
                    SELECT COUNT(*) FROM tom_snapshots
                    WHERE entity_id IN (?, ?)
                    """,
                    (ghost_id, canonical_id),
                )
            ).fetchone()
            canonical_assertions = await (
                await db.execute(
                    """
                    SELECT COUNT(*) FROM tom_trait_assertions
                    WHERE entity_id = ?
                    """,
                    (canonical_id,),
                )
            ).fetchone()
        assert snapshot_count[0] == 0
        assert canonical_assertions[0] == 2


@pytest.mark.asyncio
async def test_tom_ghost_rewrite_keeps_distinct_project_scopes_current() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="person:alice-canon",
            canonical_name="Alice",
            entity_type="person",
        )
        ghost_id = _canonical_entity_id("person", "Alice")
        store = L2CognitionStore(db_path=db_path)
        now = time.time()
        project_a = {
            "all_of": [
                {
                    "dimension": "project",
                    "context_id": f"ctx_project_{'a' * 64}",
                }
            ]
        }
        project_b = {
            "all_of": [
                {
                    "dimension": "project",
                    "context_id": f"ctx_project_{'b' * 64}",
                }
            ]
        }
        for entity_id, value, event_id, project in (
            (ghost_id, "happy", "evt-project-a", project_a),
            ("person:alice-canon", "focused", "evt-project-b", project_b),
        ):
            await store.upsert_assertion_candidate(
                {
                    "entity_id": entity_id,
                    "entity_type": "person",
                    "trait_family": "mood",
                    "trait_name": "mood",
                    "trait_value": value,
                    "confidence_score": 0.8,
                    "validation_state": "tentative",
                    "temporal_scope": "session",
                    "decay_policy": "session_decay",
                    "evidence_events": [event_id],
                    "volatility_index": 0.5,
                    "source_domain": "chat",
                    "inference_depth": "direct",
                    "first_inferred_at": now,
                    "last_validated_at": now,
                    "scope": project,
                }
            )

        stats = await L2EntityMaintenance(db_path=db_path).run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.tom_entity_refs_rewritten >= 1

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("""
                    SELECT entity_id, trait_value, scope_key, status
                    FROM tom_trait_assertions
                    WHERE entity_id = 'person:alice-canon'
                      AND status NOT IN (
                          'superseded', 'archived', 'expired',
                          'user_rejected', 'shadow'
                      )
                    ORDER BY scope_key
                    """)).fetchall()
        assert len(rows) == 2
        assert {row["trait_value"] for row in rows} == {"happy", "focused"}
        assert {row["scope_key"] for row in rows} == {
            scope_key(project_a),
            scope_key(project_b),
        }


@pytest.mark.asyncio
async def test_tom_ghost_rewrite_accumulates_evidence_from_all_collisions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        canonical_id = "person:alice-canon"
        await catalog.upsert_entity(
            entity_id=canonical_id,
            canonical_name="Alice",
            entity_type="person",
        )
        ghost_id = _canonical_entity_id("person", "Alice")
        store = L2CognitionStore(db_path=db_path)
        now = time.time()
        candidates = (
            (ghost_id, canonical_id, "evt-ghost-subject", 0.7),
            (canonical_id, ghost_id, "evt-ghost-target", 0.8),
            (canonical_id, canonical_id, "evt-canonical", 0.95),
        )
        for entity_id, target_entity_id, event_id, confidence in candidates:
            await store.upsert_assertion_candidate(
                {
                    "entity_id": entity_id,
                    "entity_type": "person",
                    "trait_family": "relationship_model",
                    "trait_name": "relationship.trust",
                    "trait_value": "high",
                    "target_entity_id": target_entity_id,
                    "target_entity_type": "person",
                    "confidence_score": confidence,
                    "validation_state": "tentative",
                    "temporal_scope": "persistent",
                    "evidence_events": [event_id],
                    "volatility_index": 0.2,
                    "source_domain": "chat",
                    "inference_depth": "direct",
                    "first_inferred_at": now,
                    "last_validated_at": now,
                }
            )

        stats = await L2EntityMaintenance(db_path=db_path).run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.tom_entity_refs_rewritten >= 1

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (
                await db.execute(
                    """
                    SELECT entity_id, target_entity_id, evidence_events, status
                    FROM tom_trait_assertions
                    WHERE entity_id = ? AND target_entity_id = ?
                    ORDER BY assertion_id
                    """,
                    (canonical_id, canonical_id),
                )
            ).fetchall()
        current = [row for row in rows if row["status"] != "superseded"]
        assert len(current) == 1
        assert set(json.loads(current[0]["evidence_events"])) == {
            "evt-ghost-subject",
            "evt-ghost-target",
            "evt-canonical",
        }
        assert sum(row["status"] == "superseded" for row in rows) == 2


@pytest.mark.asyncio
async def test_tom_ghost_rewrite_handles_invalidated_unique_collision() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        canonical_id = "person:alice-canon"
        await catalog.upsert_entity(
            entity_id=canonical_id,
            canonical_name="Alice",
            entity_type="person",
        )
        ghost_id = _canonical_entity_id("person", "Alice")
        store = L2CognitionStore(db_path=db_path)
        now = time.time()
        invalidated_id = await store.upsert_assertion_candidate(
            {
                "entity_id": ghost_id,
                "entity_type": "person",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "happy",
                "confidence_score": 0.99,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "evidence_events": ["evt-invalidated-ghost"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )
        await store.upsert_assertion_candidate(
            {
                "entity_id": canonical_id,
                "entity_type": "person",
                "trait_family": "mood",
                "trait_name": "mood",
                "trait_value": "calm",
                "confidence_score": 0.4,
                "validation_state": "tentative",
                "temporal_scope": "session",
                "evidence_events": ["evt-current-canonical"],
                "volatility_index": 0.5,
                "source_domain": "chat",
                "inference_depth": "direct",
                "first_inferred_at": now,
                "last_validated_at": now,
            }
        )
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET status = 'invalidated' WHERE assertion_id = ?",
                (invalidated_id,),
            )
            await db.commit()

        stats = await L2EntityMaintenance(db_path=db_path).run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.tom_entity_refs_rewritten >= 1

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (
                await db.execute(
                    """
                    SELECT assertion_id, entity_id, trait_value, status
                    FROM tom_trait_assertions
                    WHERE entity_id = ?
                    ORDER BY assertion_id
                    """,
                    (canonical_id,),
                )
            ).fetchall()
        assert len(rows) == 2
        assert [row["trait_value"] for row in rows if row["status"] != "superseded"] == ["calm"]
        assert (
            next(row for row in rows if row["assertion_id"] == invalidated_id)["status"]
            == "superseded"
        )


@pytest.mark.asyncio
async def test_forgotten_assertion_history_stays_governed_after_ghost_rekey() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="person:alice-canonical",
            canonical_name="Alice",
            entity_type="person",
        )
        ghost_id = _canonical_entity_id("person", "Alice")
        store = L2CognitionStore(db_path=db_path)
        observed_at = time.time() - 120
        assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": ghost_id,
                "entity_type": "person",
                "trait_family": "preference_profile",
                "trait_name": "drink.preference",
                "trait_value": "tea",
                "confidence_score": 0.8,
                "evidence_events": ["evt-ghost-tea"],
                "volatility_index": 0.2,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "validation_state": "corroborated",
                "first_inferred_at": observed_at,
                "last_validated_at": observed_at,
                "temporal_scope": "persistent",
            }
        )
        old_slot = assertion_slot_key(
            entity_type="person",
            entity_id=ghost_id,
            trait_name="drink.preference",
        )
        old_replacement_fingerprint = assertion_claim_fingerprint(
            slot_key_value=old_slot,
            trait_value="coffee",
        )
        corrected = await store.apply_assertion_correction(
            assertion_id=assertion_id,
            request_id="correct-ghost-drink",
            actor_id="user:self",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="coffee",
            source_event_id="evt-ghost-coffee-correction",
        )
        assert corrected is not None
        correction_id = corrected["correction"]["correction_id"]
        replacement_id = corrected["current_assertion"]["assertion_id"]

        await store.forget_entity(entity_id=ghost_id)
        stats = await L2EntityMaintenance(db_path=db_path).run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            clean_stale_snapshots=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.tom_entity_refs_rewritten == 1

        new_slot = assertion_slot_key(
            entity_type="person",
            entity_id="person:alice-canonical",
            trait_name="drink.preference",
        )
        new_tea_fingerprint = assertion_claim_fingerprint(
            slot_key_value=new_slot,
            trait_value="tea",
        )
        new_coffee_fingerprint = assertion_claim_fingerprint(
            slot_key_value=new_slot,
            trait_value="coffee",
        )
        history = await store.get_assertion_correction_history(slot_key=new_slot)
        stale_history = await store.get_assertion_correction_history(slot_key=old_slot)
        assert {row["assertion_id"] for row in history["assertions"]} == {
            assertion_id,
            replacement_id,
        }
        assert [row["correction_id"] for row in history["corrections"]] == [correction_id]
        assert stale_history == {"assertions": [], "corrections": []}

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (
                await db.execute(
                    """
                    SELECT assertion_id, entity_id, slot_key, claim_fingerprint, status
                    FROM tom_trait_assertions
                    WHERE assertion_id IN (?, ?)
                    ORDER BY assertion_id
                    """,
                    (assertion_id, replacement_id),
                )
            ).fetchall()
            correction = await (
                await db.execute(
                    "SELECT * FROM memory_corrections WHERE correction_id = ?",
                    (correction_id,),
                )
            ).fetchone()
            rules = await (await db.execute("""
                    SELECT claim_fingerprint, semantic_fingerprint
                    FROM memory_forget_claim_rules
                    WHERE target_kind = 'assertion'
                    ORDER BY claim_fingerprint
                    """)).fetchall()
            stale_governance = await (
                await db.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM memory_forget_claim_rules
                         WHERE target_kind = 'assertion'
                           AND claim_fingerprint = ?) +
                        (SELECT COUNT(*) FROM memory_claim_evidence_events
                         WHERE target_kind = 'assertion'
                           AND claim_fingerprint = ?)
                    """,
                    (old_replacement_fingerprint, old_replacement_fingerprint),
                )
            ).fetchone()

        assert len(rows) == 2
        assert all(row["entity_id"] == "person:alice-canonical" for row in rows)
        assert all(row["slot_key"] == new_slot for row in rows)
        assert all(row["status"] == "archived" for row in rows)
        assert correction is not None
        assert correction["slot_key"] == new_slot
        assert json.loads(correction["before_json"])["entity_id"] == "person:alice-canonical"
        assert {row["claim_fingerprint"] for row in rules} == {
            new_tea_fingerprint,
            new_coffee_fingerprint,
        }
        assert all(row["claim_fingerprint"] == row["semantic_fingerprint"] for row in rules)
        assert stale_governance[0] == 0

        for value, event_id in (
            ("tea", "evt-ghost-tea"),
            ("coffee", "evt-ghost-coffee-correction"),
        ):
            replayed = await store.upsert_assertion_candidate(
                {
                    "entity_id": "person:alice-canonical",
                    "entity_type": "person",
                    "trait_family": "preference_profile",
                    "trait_name": "drink.preference",
                    "trait_value": value,
                    "confidence_score": 0.9,
                    "evidence_events": [event_id],
                    "volatility_index": 0.2,
                    "source_domain": "conversation",
                    "inference_depth": "semantic",
                    "validation_state": "corroborated",
                    "first_inferred_at": time.time(),
                    "last_validated_at": time.time(),
                    "temporal_scope": "persistent",
                }
            )
            assert replayed.startswith("blocked:")
        assert await store.list_current_assertions(entity_id="person:alice-canonical") == []


@pytest.mark.asyncio
async def test_target_only_ghost_rekeys_forgotten_assertion_governance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)
        catalog = L2EntityCatalog(db_path=db_path)
        await catalog.upsert_entity(
            entity_id="person:alice-canonical",
            canonical_name="Alice",
            entity_type="person",
        )
        ghost_id = _canonical_entity_id("person", "Alice")
        store = L2CognitionStore(db_path=db_path)
        observed_at = time.time() - 60
        assertion_id = await store.upsert_assertion_candidate(
            {
                "entity_id": "user:self",
                "entity_type": "user",
                "trait_family": "relationship_model",
                "trait_name": "relationship.trust",
                "trait_value": "high",
                "target_entity_id": ghost_id,
                "target_entity_type": "person",
                "confidence_score": 0.8,
                "evidence_events": ["evt-target-only-ghost"],
                "volatility_index": 0.2,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "validation_state": "corroborated",
                "first_inferred_at": observed_at,
                "last_validated_at": observed_at,
                "temporal_scope": "persistent",
            }
        )
        await store.forget_entity(entity_id=ghost_id)
        stats = await L2EntityMaintenance(db_path=db_path).run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            clean_stale_snapshots=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.tom_entity_refs_rewritten == 1

        new_slot = assertion_slot_key(
            entity_type="user",
            entity_id="user:self",
            trait_name="relationship.trust",
            target_entity_id="person:alice-canonical",
        )
        new_fingerprint = assertion_claim_fingerprint(
            slot_key_value=new_slot,
            trait_value="high",
        )
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            assertion = await (
                await db.execute(
                    "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                    (assertion_id,),
                )
            ).fetchone()
            rule = await (
                await db.execute(
                    """
                    SELECT * FROM memory_forget_claim_rules
                    WHERE target_kind = 'assertion' AND claim_fingerprint = ?
                    """,
                    (new_fingerprint,),
                )
            ).fetchone()
        assert assertion is not None
        assert assertion["target_entity_id"] == "person:alice-canonical"
        assert assertion["target_entity_type"] == "person"
        assert assertion["slot_key"] == new_slot
        assert assertion["status"] == "archived"
        assert rule is not None
        assert rule["semantic_fingerprint"] == new_fingerprint

        replayed = await store.upsert_assertion_candidate(
            {
                "entity_id": "user:self",
                "entity_type": "user",
                "trait_family": "relationship_model",
                "trait_name": "relationship.trust",
                "trait_value": "high",
                "target_entity_id": "person:alice-canonical",
                "target_entity_type": "person",
                "confidence_score": 0.9,
                "evidence_events": ["evt-target-only-ghost"],
                "volatility_index": 0.2,
                "source_domain": "conversation",
                "inference_depth": "semantic",
                "validation_state": "corroborated",
                "first_inferred_at": time.time(),
                "last_validated_at": time.time(),
                "temporal_scope": "persistent",
            }
        )
        assert replayed.startswith("blocked:")
        assert (
            await store.list_current_assertions(
                entity_id="user:self",
                target_entity_id="person:alice-canonical",
            )
            == []
        )


# -----------------------------------------------------------------------
# Concurrent run lock
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_run_is_skipped():
    """A second concurrent run() call should be skipped while the first is running."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        maint = L2EntityMaintenance(db_path=db_path)

        # Acquire the lock manually to simulate a running maintenance
        await maint._run_lock.acquire()
        try:
            # Second run should return immediately with empty stats
            stats = await maint.run()
            assert stats.ghost_edges_rewritten == 0
            assert stats.fragment_entities_merged == 0
            assert stats.orphans_pruned == 0
        finally:
            maint._run_lock.release()


# ── Archive stale edges ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_stale_low_confidence_edges():
    """Edges with low confidence and old updated_at should be archived."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        now = time.time()
        old_ts = now - 100 * 86400  # 100 days ago

        async with sqlite_connection_async(db_path) as db:
            # Low confidence + old → should be archived
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status, fact_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "triple_archive_low",
                    "user:self",
                    "user",
                    "LIKES",
                    "food:sushi",
                    "food",
                    0.2,
                    "[]",
                    3,
                    old_ts,
                    old_ts,
                    old_ts,
                    old_ts,
                    "active",
                    "explicit_fact",
                ),
            )
            # Single observation + very old → should be archived
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status, fact_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "triple_archive_single",
                    "user:self",
                    "user",
                    "KNOWS",
                    "person:bob",
                    "person",
                    0.8,
                    "[]",
                    1,
                    now - 200 * 86400,
                    now - 200 * 86400,
                    now - 200 * 86400,
                    now - 200 * 86400,
                    "active",
                    "explicit_fact",
                ),
            )
            # Recent high-confidence → should stay active
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status, fact_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "triple_keep_active",
                    "user:self",
                    "user",
                    "USES",
                    "software:vscode",
                    "software",
                    0.9,
                    "[]",
                    5,
                    now,
                    now,
                    now,
                    now,
                    "active",
                    "explicit_fact",
                ),
            )
            # future_intent should NOT be archived (has its own TTL)
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status, fact_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "triple_future",
                    "user:self",
                    "user",
                    "WANTS_TO",
                    "activity:travel",
                    "activity",
                    0.1,
                    "[]",
                    1,
                    old_ts,
                    old_ts,
                    old_ts,
                    old_ts,
                    "active",
                    "future_intent",
                ),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
        )
        assert stats.edges_archived == 2

        async with sqlite_connection_async(db_path) as db:
            async with db.execute(
                "SELECT triple_id, status FROM knowledge_graph ORDER BY triple_id"
            ) as cur:
                rows = {r[0]: r[1] for r in await cur.fetchall()}

        assert rows["triple_archive_low"] == "archived"
        assert rows["triple_archive_single"] == "archived"
        assert rows["triple_keep_active"] == "active"
        assert rows["triple_future"] == "active"


@pytest.mark.asyncio
async def test_archive_stale_edges_preserves_user_authority_and_future_validity(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    now = time.time()
    original_id = await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["evt-original-city"],
        confidence=0.8,
        observed_at=now - 10,
        source_type="chat",
    )
    corrected = await store.apply_relationship_correction(
        triple_id=original_id,
        request_id="correct-stale-city",
        actor_id="user:self",
        correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"object_id": "place:shanghai", "object_type": "place"},
    )
    assert corrected is not None
    authoritative_id = corrected["current_relationship"]["triple_id"]

    future_id = await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="WORKS_AT",
        object_id="organization:future-employer",
        object_type="organization",
        evidence_event_ids=["evt-future-employer"],
        confidence=0.2,
        observed_at=now - 200 * 86400,
        valid_from=now + 30 * 86400,
        source_type="calendar",
    )
    ordinary_id = await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="KNOWS",
        object_id="person:old-contact",
        object_type="person",
        evidence_event_ids=["evt-old-contact"],
        confidence=0.2,
        observed_at=now - 200 * 86400,
        source_type="sensor",
    )
    stale_at = now - 200 * 86400
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "UPDATE knowledge_graph SET updated_at = ? WHERE triple_id IN (?, ?, ?)",
            (stale_at, authoritative_id, future_id, ordinary_id),
        )
        await db.commit()

    maint = L2EntityMaintenance(db_path=store.db_path, cognition_store=store)
    stats = await maint.run(
        resolve_ghosts=False,
        merge_fragments=False,
        prune_orphans=False,
        expire_future_intents=False,
        expire_decayed_assertions=False,
        clean_stale_snapshots=False,
        reconcile_stale=False,
        consolidate_open_predicates=False,
        purge_terminal_edges=False,
    )

    authoritative = await store.get_relationship(triple_id=authoritative_id)
    future = await store.get_relationship(triple_id=future_id)
    ordinary = await store.get_relationship(triple_id=ordinary_id)
    assert stats.edges_archived == 1
    assert authoritative["status"] == "active"
    assert future["status"] == "active"
    assert ordinary["status"] == "archived"

    supported_id = await store.upsert_knowledge_edge(
        subject_id="user:self",
        subject_type="user",
        predicate="LIVES_IN",
        object_id="place:shanghai",
        object_type="place",
        evidence_event_ids=["evt-current-city-support"],
        confidence=0.7,
        observed_at=now + 1,
        source_type="chat",
    )
    supported = await store.get_relationship(triple_id=supported_id)
    assert supported_id == authoritative_id
    assert supported["status"] == "active"
    assert supported["evidence_event_ids"] == ["evt-current-city-support"]
    assert supported["observation_count"] == 2


@pytest.mark.asyncio
async def test_archived_edge_warms_back_on_new_evidence():
    """An archived edge should become active again when upsert_knowledge_edge receives new evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        now = time.time()
        old_ts = now - 100 * 86400

        # Compute the same triple_id that upsert_knowledge_edge will use
        import uuid as _uuid

        triple_id = f"triple_{_uuid.uuid5(_uuid.NAMESPACE_DNS, 'user:self:LIKES:food:ramen')}"

        # Insert an archived edge directly
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                """
                INSERT INTO knowledge_graph(
                    triple_id, subject_id, subject_type, predicate, object_id, object_type,
                    confidence, evidence_event_ids, observation_count,
                    first_observed_at, last_observed_at, created_at, updated_at, status, fact_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    triple_id,
                    "user:self",
                    "user",
                    "LIKES",
                    "food:ramen",
                    "food",
                    0.2,
                    json.dumps(["e_old"]),
                    2,
                    old_ts,
                    old_ts,
                    old_ts,
                    old_ts,
                    "archived",
                    "explicit_fact",
                ),
            )
            await db.commit()

        store = L2CognitionStore(db_path=db_path)
        await store.initialize()

        # Upsert with the same (subject, predicate, object) — should warm back
        await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:ramen",
            object_type="food",
            confidence=0.7,
            evidence_event_ids=["e_new"],
            observed_at=now,
            source_type="test",
        )

        async with sqlite_connection_async(db_path) as db:
            db.row_factory = None
            async with db.execute(
                "SELECT status, observation_count, confidence FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cur:
                row = await cur.fetchone()

        assert row is not None
        assert row[0] == "active", f"Expected 'active' but got '{row[0]}'"
        assert row[1] == 3  # was 2, +1
        assert row[2] > 0.2  # confidence should have increased


@pytest.mark.asyncio
async def test_maintenance_does_not_embed_pending_edges() -> None:
    """Regression: L2EntityMaintenance.run() must NOT embed pending edges.

    EdgeEmbeddingDrainer is now the sole embedder.  Even when the maintenance
    instance is wired with a real (mocked) embedding_service + edge_vector_index,
    running full maintenance must leave a pending edge in its 'pending' state.
    """
    from unittest.mock import AsyncMock, MagicMock

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        await store.upsert_knowledge_edge(
            subject_id="user:self",
            subject_type="user",
            predicate="LIKES",
            object_id="food:tacos",
            object_type="food",
            evidence_event_ids=["evt-regression-1"],
            confidence=0.7,
            observed_at=time.time(),
            source_type="chat",
            evidence_text="I really like tacos",
        )

        # Confirm the edge starts as pending
        pending_before = await store.get_pending_edge_embeddings(limit=10)
        assert len(pending_before) == 1

        # Wire maintenance with mocked embedding infra (same pattern as the old
        # test_embed_pending_edges_calls_pipeline_and_updates_status test).
        # Before the fix, maintenance would have called _embed_pending_edges and
        # embedded the edge; after the fix it must leave it pending.
        mock_embedding_service = MagicMock()
        mock_vector_index = MagicMock()

        mock_result = MagicMock()
        mock_result.parent_id = pending_before[0]["triple_id"]
        mock_result.embedded_at = time.time()
        mock_result.embeddings = [[0.1, 0.2, 0.3]]
        mock_embedding_service.profile_from_result.return_value = SimpleNamespace(
            profile_id="test-profile"
        )

        mock_pipeline_cls = AsyncMock()
        mock_pipeline_cls.upsert_items = AsyncMock(return_value=[mock_result])

        maint = L2EntityMaintenance(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        import magi.memory.l2.entities.maintenance as em_module

        original_pipeline = em_module.MemoryEmbeddingPipeline
        em_module.MemoryEmbeddingPipeline = lambda **kwargs: mock_pipeline_cls

        try:
            await maint.run()
        finally:
            em_module.MemoryEmbeddingPipeline = original_pipeline

        # Edge must STILL be pending — maintenance must not have embedded it.
        pending_after = await store.get_pending_edge_embeddings(limit=10)
        assert len(pending_after) == 1, (
            "maintenance.run() must not embed pending edges; "
            "EdgeEmbeddingDrainer is now the sole embedder"
        )
