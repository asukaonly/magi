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
async def test_embed_pending_edges_skips_when_no_embedding_service() -> None:
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
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
        )
        assert stats.edges_embedded == 0

        # Verify edge still has pending status
        edges = await store.get_pending_edge_embeddings(limit=10)
        assert len(edges) == 1
        assert edges[0]["embedding_status"] == "pending"


@pytest.mark.asyncio
async def test_embed_pending_edges_calls_pipeline_and_updates_status() -> None:
    from unittest.mock import AsyncMock, MagicMock

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "m.db")
        await _init_schema(db_path)

        store = L2CognitionStore(db_path=db_path)
        tid = await store.upsert_knowledge_edge(
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

        mock_result = MagicMock()
        mock_result.parent_id = tid
        mock_result.embedded_at = time.time()

        mock_pipeline_cls = AsyncMock()
        mock_pipeline_cls.upsert_items = AsyncMock(return_value=[mock_result])

        maint = L2EntityMaintenance(
            db_path=db_path,
            embedding_service=mock_embedding_service,
            edge_vector_index=mock_vector_index,
        )

        import magi.memory.l2.entity_maintenance as em_module
        original_pipeline = em_module.MemoryEmbeddingPipeline
        em_module.MemoryEmbeddingPipeline = lambda **kwargs: mock_pipeline_cls

        try:
            stats = await maint.run(
                resolve_ghosts=False,
                merge_fragments=False,
                prune_orphans=False,
                expire_future_intents=False,
                consolidate_open_predicates=False,
            )
        finally:
            em_module.MemoryEmbeddingPipeline = original_pipeline

        assert stats.edges_embedded == 1

        edges = await store.get_pending_edge_embeddings(limit=10)
        assert len(edges) == 0

        async with sqlite_connection_async(db_path) as db:
            async with db.execute(
                "SELECT embedding_status FROM knowledge_graph WHERE triple_id = ?",
                (tid,),
            ) as cur:
                row = await cur.fetchone()
        assert row is not None
        assert row[0] == "ready"


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
        recent_time = now - 1 * 3600  # 1 hour ago (< 4h)

        # Old fast_decay assertion — should be expired
        await store.upsert_assertion_candidate({
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
        })
        # Backdate the updated_at
        async with sqlite_connection_async(db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET updated_at = ? WHERE entity_id = 'user:u1' AND trait_name = 'annoyance'",
                (old_time,),
            )
            await db.commit()

        # Recent fast_decay assertion — should survive
        await store.upsert_assertion_candidate({
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
        })
        # This one was updated recently, no need to backdate

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            consolidate_open_predicates=False,
            embed_edges=False,
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

        await store.upsert_assertion_candidate({
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
        })
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
            embed_edges=False,
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

        await store.upsert_assertion_candidate({
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
        })
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
            embed_edges=False,
        )

        assert stats.expired_assertions == 0

        assertions = await store.list_tom_assertions(entity_id="user:u1")
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
        await store.upsert_assertion_candidate({
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
        })
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
            embed_edges=False,
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
        await store.upsert_assertion_candidate({
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
        })

        maint = L2EntityMaintenance(db_path=db_path, cognition_store=store)
        stats = await maint.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            consolidate_open_predicates=False,
            embed_edges=False,
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
                (tid_open, "user:self", "user", "ADORES", "food:ramen", "food",
                 0.6, json.dumps(["evt-open-1", "evt-open-2"]), 2,
                 now, now, now, now, "active"),
            )
            await db.commit()

        # Patch synonym group so ADORES maps to "affinity" group (which contains LIKES)
        original_fn = __import__("magi.memory.l2.ontology", fromlist=["get_predicate_synonym_group"]).get_predicate_synonym_group

        def patched_synonym_group(predicate: str) -> str | None:
            if predicate.strip().upper() == "ADORES":
                return "affinity"
            return original_fn(predicate)

        with patch("magi.memory.l2.entity_maintenance.get_predicate_synonym_group", side_effect=patched_synonym_group):
            maint = L2EntityMaintenance(db_path=db_path)
            stats = await maint.run(
                resolve_ghosts=False,
                merge_fragments=False,
                prune_orphans=False,
                expire_future_intents=False,
                expire_decayed_assertions=False,
                reconcile_stale=False,
                embed_edges=False,
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
        await store.upsert_assertion_candidate({
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
        })

        # Insert assertion for the target entity with same trait key (lower confidence)
        await store.upsert_assertion_candidate({
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
        })

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
            embed_edges=False,
        )

        assert stats.tom_entity_refs_rewritten >= 1

        # Only one assertion should remain for the canonical entity
        assertions = await store.list_tom_assertions(entity_id="person:alice-canon")
        assert len(assertions) == 1
        # The ghost had higher confidence, so its value should win
        assert assertions[0]["trait_value"] == "happy"
        assert assertions[0]["confidence_score"] == 0.9


# -----------------------------------------------------------------------
# Concurrent run lock
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_run_is_skipped():
    """A second concurrent run() call should be skipped while the first is running."""
    import asyncio

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
                    "triple_archive_low", "user:self", "user", "LIKES", "food:sushi", "food",
                    0.2, "[]", 3,
                    old_ts, old_ts, old_ts, old_ts, "active", "explicit_fact",
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
                    "triple_archive_single", "user:self", "user", "KNOWS", "person:bob", "person",
                    0.8, "[]", 1,
                    now - 200 * 86400, now - 200 * 86400, now - 200 * 86400, now - 200 * 86400,
                    "active", "explicit_fact",
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
                    "triple_keep_active", "user:self", "user", "USES", "software:vscode", "software",
                    0.9, "[]", 5,
                    now, now, now, now, "active", "explicit_fact",
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
                    "triple_future", "user:self", "user", "WANTS_TO", "activity:travel", "activity",
                    0.1, "[]", 1,
                    old_ts, old_ts, old_ts, old_ts, "active", "future_intent",
                ),
            )
            await db.commit()

        maint = L2EntityMaintenance(db_path=db_path)
        stats = await maint.run(
            resolve_ghosts=False, merge_fragments=False, prune_orphans=False,
            expire_future_intents=False, expire_decayed_assertions=False,
            reconcile_stale=False, consolidate_open_predicates=False,
            embed_edges=False,
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
                    triple_id, "user:self", "user", "LIKES", "food:ramen", "food",
                    0.2, json.dumps(["e_old"]), 2,
                    old_ts, old_ts, old_ts, old_ts, "archived", "explicit_fact",
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
