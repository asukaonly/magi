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


# ---------------------------------------------------------------------------
# Fact kind admission check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra,method,evidence,expected",
    [
        ({"fact_kind": "public_topology"}, "structured_hint", None, "public_topology"),
        ({"fact_kind": "public_topology"}, "rule", None, "public_topology"),
        ({"fact_kind": "public_topology"}, "llm_phase2_integration", None, "explicit_fact"),
        ({"fact_kind": "stable_preference"}, "rule", None, "stable_preference"),
        ({"fact_kind": "stable_preference"}, "llm_phase1_fast_track", None, "explicit_fact"),
        (
            {"fact_kind": "interaction_evidence"},
            "llm_phase2_integration",
            None,
            "interaction_evidence",
        ),
        ({}, "rule", None, "explicit_fact"),
        ({"fact_kind": None}, "rule", None, "explicit_fact"),
        ({"fact_kind": ""}, "rule", None, "explicit_fact"),
        (
            {"fact_kind": "stable_preference"},
            "llm_phase1_grounded",
            "user_self_report",
            "stable_preference",
        ),
        (
            {"fact_kind": "stable_preference"},
            "llm_phase1_grounded",
            "external_observation",
            "explicit_fact",
        ),
        (
            {"fact_kind": "public_topology"},
            "llm_phase1_grounded",
            "user_self_report",
            "explicit_fact",
        ),
    ],
)
async def test_fact_admission_persists_source_authority_decision(
    tmp_path, extra, method, evidence, expected
):
    from magi.memory.l2.store import L2CognitionStore

    path = str(tmp_path / "l2.db")
    store = L2CognitionStore(db_path=path)
    await store.initialize()
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="KNOWS",
        object_id="person:alice",
        object_type="person",
        evidence_event_ids=["e1"],
        confidence=0.9,
        observed_at=time.time(),
        source_type="conversation",
        extraction_method=method,
        evidence_class=evidence,
        **extra
    )
    async with aiosqlite.connect(path) as db:
        rows = await (
            await db.execute("SELECT triple_id,fact_kind FROM knowledge_graph")
        ).fetchall()
    assert rows == [(triple_id, expected)]


# ---------------------------------------------------------------------------
# memory_subdomain classification
# ---------------------------------------------------------------------------


class TestClassifyMemorySubdomain:
    """Unit tests for classify_memory_subdomain helper."""

    @pytest.mark.parametrize(
        "expected_subdomain,scope_value,decay_value",
        [
            pytest.param("semantic", "stable", "evidence_only", id="stable_evidence_only_is_semantic"),
            pytest.param("semantic", "persistent", "none", id="persistent_none_is_semantic"),
            pytest.param("semantic", "", "", id="empty_scope_empty_policy_is_semantic"),
            pytest.param("state", "session", "session_decay", id="session_decay_is_state"),
            pytest.param("state", "momentary", "fast_decay", id="momentary_fast_decay_is_state"),
            pytest.param("state", "daily", "time_window", id="daily_time_window_is_state"),
        ],
    )
    def test_classify_memory_subdomain_respects_scope_and_decay(
        self, expected_subdomain, scope_value, decay_value
    ):
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain(scope_value, decay_value) == expected_subdomain


    def test_stable_with_session_decay_is_state(self):
        """Even with stable scope, a non-semantic decay policy produces state."""
        from magi.memory.l2.assertions.subdomain import classify_memory_subdomain

        assert classify_memory_subdomain("stable", "session_decay") == "state"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subdomain,trait,value,family,scope,decay",
    [
        ("semantic", "favorite_food", "ramen", "preference_profile", "stable", "evidence_only"),
        ("state", "mood", "happy", "mood", "session", "session_decay"),
    ],
)
async def test_assertion_storage_preserves_explicit_subdomain(
    tmp_path, subdomain, trait, value, family, scope, decay
):
    from magi.memory.l2.store import L2CognitionStore

    path = str(tmp_path / "l2.db")
    store = L2CognitionStore(db_path=path)
    await store.initialize()
    now = time.time()
    assertion_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_name": trait,
            "trait_value": value,
            "trait_family": family,
            "confidence_score": 0.7,
            "evidence_events": ["e1"],
            "volatility_index": 0.2,
            "source_domain": "conversation",
            "inference_depth": "surface",
            "validation_state": "tentative",
            "first_inferred_at": now,
            "last_validated_at": now,
            "temporal_scope": scope,
            "decay_policy": decay,
            "decay_anchor_at": now,
            "memory_subdomain": subdomain,
        }
    )
    async with aiosqlite.connect(path) as db:
        rows = await (
            await db.execute(
                "SELECT assertion_id,memory_subdomain,trait_name,trait_value FROM tom_trait_assertions"
            )
        ).fetchall()
    assert rows == [(assertion_id, subdomain, trait, value)]
