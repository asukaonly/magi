from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.entity_catalog import L2EntityCatalog
from magi.memory.l2.entity_maintenance import L2EntityMaintenance, _canonical_entity_id
from magi.memory.l2.store import L2CognitionStore


async def _init_schema(db_path: str) -> None:
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    catalog = L2EntityCatalog(db_path=db_path)
    await catalog.initialize()


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
            async with db.execute(
                "SELECT object_id FROM knowledge_graph WHERE triple_id = ?",
                ("triple_test_ghost",),
            ) as cur:
                row = await cur.fetchone()
        assert row is not None
        assert row[0] == "software:twitter-handle"


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
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            min_mentions_to_keep=99,
            resolve_ghosts=False,
            prune_orphans=False,
        )
        assert stats.fragment_entities_merged >= 1

        async with sqlite_connection_async(db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM entity_catalog WHERE LOWER(TRIM(canonical_name)) = ?",
                ("claude",),
            ) as cur:
                n = (await cur.fetchone())[0]
        assert n == 1


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
                ("Nobody", "nobody", "person", "[]", "x", "person:nobody", 0.9, now),
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
            async with db.execute("SELECT COUNT(*) FROM entity_catalog WHERE entity_id = ?", ("person:nobody",)) as cur:
                assert (await cur.fetchone())[0] == 0


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
