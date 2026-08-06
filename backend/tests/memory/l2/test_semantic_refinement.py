"""Tests for P2 — Semantic Memory Refinement.

Covers:
- Schema migration: knowledge_graph lifecycle columns, entity_facets lifecycle columns,
  tom_trait_assertions memory_subdomain column
- Fact kind admission check in upsert_knowledge_edge
- memory_subdomain classification (semantic vs state)
"""

from __future__ import annotations

import time

import aiosqlite
import pytest


# ---------------------------------------------------------------------------
# Schema migration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_graph_lifecycle_columns_exist(tmp_path):
    """P2 lifecycle columns are present after initialization."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(knowledge_graph)") as cur:
            cols = {row["name"] for row in await cur.fetchall()}

    for col in ("valid_from", "valid_to", "status_reason"):
        assert col in cols, f"Missing column: {col}"


@pytest.mark.asyncio
async def test_entity_facets_lifecycle_columns_exist(tmp_path):
    """P2 lifecycle columns are present on entity_facets after initialization."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(entity_facets)") as cur:
            cols = {row["name"] for row in await cur.fetchall()}

    for col in ("status",):
        assert col in cols, f"Missing column: {col}"


@pytest.mark.asyncio
async def test_tom_assertions_memory_subdomain_column_exists(tmp_path):
    """memory_subdomain column added to tom_trait_assertions."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(tom_trait_assertions)") as cur:
            cols = {row["name"] for row in await cur.fetchall()}

    assert "memory_subdomain" in cols


# ---------------------------------------------------------------------------
# Fact kind admission check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fact_kind_public_topology_accepted_from_structured_hint(tmp_path):
    """public_topology is accepted when extraction_method is structured_hint."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIVES_IN",
        object_id="location:tokyo",
        object_type="location",
        fact_kind="public_topology",
        evidence_event_ids=["e1"],
        confidence=0.9,
        observed_at=now,
        source_type="source_structured",
        extraction_method="structured_hint",
    )
    assert triple_id

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT fact_kind FROM knowledge_graph WHERE triple_id = ?", (triple_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row["fact_kind"] == "public_topology"


@pytest.mark.asyncio
async def test_fact_kind_public_topology_downgraded_from_llm(tmp_path):
    """public_topology is downgraded to explicit_fact when extraction_method is LLM-based."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="MEMBER_OF",
        object_id="org:acme",
        object_type="organization",
        fact_kind="public_topology",
        evidence_event_ids=["e1"],
        confidence=0.5,
        observed_at=now,
        source_type="llm",
        extraction_method="llm_phase2_integration",
    )

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT fact_kind FROM knowledge_graph WHERE triple_id = ?", (triple_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row["fact_kind"] == "explicit_fact"


@pytest.mark.asyncio
async def test_fact_kind_stable_preference_downgraded_from_llm(tmp_path):
    """stable_preference is downgraded when not from an explicit source."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="topic:jazz",
        object_type="topic",
        fact_kind="stable_preference",
        evidence_event_ids=["e1"],
        confidence=0.7,
        observed_at=now,
        source_type="llm",
        extraction_method="llm_phase1_fast_track",
    )

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT fact_kind FROM knowledge_graph WHERE triple_id = ?", (triple_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row["fact_kind"] == "explicit_fact"


@pytest.mark.asyncio
async def test_fact_kind_interaction_evidence_not_restricted(tmp_path):
    """interaction_evidence passes through regardless of extraction_method."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="TALKED_WITH",
        object_id="person:bob",
        object_type="person",
        fact_kind="interaction_evidence",
        evidence_event_ids=["e1"],
        confidence=0.8,
        observed_at=now,
        source_type="observation",
        extraction_method="llm_phase2_integration",
    )

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT fact_kind FROM knowledge_graph WHERE triple_id = ?", (triple_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row["fact_kind"] == "interaction_evidence"


@pytest.mark.asyncio
async def test_fact_kind_defaults_to_explicit_fact(tmp_path):
    """Empty/None fact_kind defaults to explicit_fact."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="KNOWS",
        object_id="person:alice",
        object_type="person",
        evidence_event_ids=["e1"],
        confidence=0.5,
        observed_at=now,
        source_type="llm",
        extraction_method="rule",
    )

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT fact_kind FROM knowledge_graph WHERE triple_id = ?", (triple_id,)
        ) as cur:
            row = await cur.fetchone()
    assert row["fact_kind"] == "explicit_fact"


# ---------------------------------------------------------------------------
# memory_subdomain classification
# ---------------------------------------------------------------------------


class TestClassifyMemorySubdomain:
    """Unit tests for classify_memory_subdomain helper."""

    def test_stable_evidence_only_is_semantic(self):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("stable", "evidence_only") == "semantic"

    def test_persistent_none_is_semantic(self):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("persistent", "none") == "semantic"

    def test_empty_scope_empty_policy_is_semantic(self):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("", "") == "semantic"

    def test_session_decay_is_state(self):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("session", "session_decay") == "state"

    def test_momentary_fast_decay_is_state(self):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("momentary", "fast_decay") == "state"

    def test_daily_time_window_is_state(self):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("daily", "time_window") == "state"

    def test_stable_with_session_decay_is_state(self):
        """Even with stable scope, a non-semantic decay policy produces state."""
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("stable", "session_decay") == "state"


@pytest.mark.asyncio
async def test_assertion_persists_memory_subdomain_semantic(tmp_path):
    """A semantic assertion (stable/evidence_only) stores memory_subdomain='semantic'."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    assertion_id = await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_name": "favorite_food",
        "trait_value": "ramen",
        "trait_family": "preference_profile",
        "confidence_score": 0.7,
        "evidence_events": ["e1"],
        "volatility_index": 0.2,
        "source_domain": "conversation",
        "inference_depth": "surface",
        "validation_state": "tentative",
        "first_inferred_at": now,
        "last_validated_at": now,
        "temporal_scope": "stable",
        "decay_policy": "evidence_only",
        "decay_anchor_at": now,
        "memory_subdomain": "semantic",
    })

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT memory_subdomain FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cur:
            row = await cur.fetchone()
    assert row["memory_subdomain"] == "semantic"


@pytest.mark.asyncio
async def test_assertion_persists_memory_subdomain_state(tmp_path):
    """A state assertion (session/session_decay) stores memory_subdomain='state'."""
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    now = time.time()

    assertion_id = await store.upsert_assertion_candidate({
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_name": "mood",
        "trait_value": "happy",
        "trait_family": "mood",
        "confidence_score": 0.6,
        "evidence_events": ["e1"],
        "volatility_index": 0.8,
        "source_domain": "conversation",
        "inference_depth": "surface",
        "validation_state": "tentative",
        "first_inferred_at": now,
        "last_validated_at": now,
        "temporal_scope": "session",
        "decay_policy": "session_decay",
        "decay_anchor_at": now,
        "memory_subdomain": "state",
    })

    async with aiosqlite.connect(str(tmp_path / "l2.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT memory_subdomain FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cur:
            row = await cur.fetchone()
    assert row["memory_subdomain"] == "state"


@pytest.mark.asyncio
async def test_validate_fact_kind_static_method():
    """Direct test of the _validate_fact_kind static method."""
    from magi.memory.l2.store import L2CognitionStore

    # public_topology from structured_hint → accepted
    assert L2CognitionStore._validate_fact_kind("public_topology", "structured_hint", 0.9) == "public_topology"
    # public_topology from rule → accepted
    assert L2CognitionStore._validate_fact_kind("public_topology", "rule", 0.5) == "public_topology"
    # public_topology from LLM → downgraded
    assert L2CognitionStore._validate_fact_kind("public_topology", "llm_phase2_integration", 0.5) == "explicit_fact"
    # stable_preference from rule → accepted
    assert L2CognitionStore._validate_fact_kind("stable_preference", "rule", 0.5) == "stable_preference"
    # stable_preference from LLM → downgraded
    assert L2CognitionStore._validate_fact_kind("stable_preference", "llm_phase1_fast_track", 0.5) == "explicit_fact"
    # interaction_evidence from any → accepted
    assert L2CognitionStore._validate_fact_kind("interaction_evidence", "llm_phase2_integration", 0.5) == "interaction_evidence"
    # empty → empty (caller handles default)
    assert L2CognitionStore._validate_fact_kind("", "rule", 0.5) == ""
