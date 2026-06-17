"""Tests for graph-derived assertion rules."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertions.derived_rules import (
    GraphDerivedAssertionRule,
    evaluate_graph_derived_assertion_rule,
)


async def _seed_edge(
    store: Any,
    *,
    object_id: str,
    event_ids: list[str],
    predicate: str = "INTERESTED_IN",
    object_type: str = "topic",
    source_type: str = "chrome_history",
    entity_id: str = "user:self",
    confidence: float = 0.8,
) -> None:
    now = time.time()
    for index, event_id in enumerate(event_ids):
        await store.upsert_knowledge_edge(
            subject_id=entity_id,
            subject_type="user",
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            evidence_event_ids=[event_id],
            confidence=confidence,
            observed_at=now + index * 0.001,
            source_type=source_type,
        )


async def _seed_canonical_name(
    store: Any,
    *,
    entity_id: str,
    canonical_name: str,
    entity_type: str = "topic",
) -> None:
    now = time.time()
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO entity_catalog(entity_id, canonical_name, entity_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                entity_type = excluded.entity_type,
                updated_at = excluded.updated_at
            """,
            (entity_id, canonical_name, entity_type, now, now),
        )
        await db.commit()


async def _assertions_for(store: Any, *, entity_id: str = "user:self") -> list[dict[str, Any]]:
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tom_trait_assertions WHERE entity_id = ? ORDER BY created_at ASC",
            (entity_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


def _interest_rule(*, min_observations: int = 3) -> GraphDerivedAssertionRule:
    return GraphDerivedAssertionRule(
        rule_id="builtin.interest",
        source_predicates=("INTERESTED_IN",),
        trait_family="preference_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=min_observations,
        source_domains=("external_activity",),
        value_strategy="canonical_name",
    )


@pytest.mark.asyncio
async def test_rule_filters_by_observation_threshold(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(store, object_id="topic:python", event_ids=["py-1", "py-2", "py-3"])
    await _seed_canonical_name(store, entity_id="topic:python", canonical_name="Python")
    await _seed_edge(store, object_id="topic:fortran", event_ids=["ft-1", "ft-2"])
    await _seed_canonical_name(store, entity_id="topic:fortran", canonical_name="Fortran")

    stats = await evaluate_graph_derived_assertion_rule(store, _interest_rule())

    assert stats["edges_seen"] == 2
    assert stats["assertions_written"] == 1
    assertions = await _assertions_for(store)
    assert [item["trait_name"] for item in assertions] == ["interest.python"]
    assert assertions[0]["trait_value"] == "Python"
    assert assertions[0]["source_domain"] == "external_activity"


@pytest.mark.asyncio
async def test_rule_is_idempotent(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(store, object_id="topic:rust", event_ids=["rs-1", "rs-2", "rs-3"])
    await _seed_canonical_name(store, entity_id="topic:rust", canonical_name="Rust")

    first = await evaluate_graph_derived_assertion_rule(store, _interest_rule())
    second = await evaluate_graph_derived_assertion_rule(store, _interest_rule())

    assert first["assertions_written"] == 1
    assert second["assertions_written"] == 1
    assertions = await _assertions_for(store)
    assert [item["trait_name"] for item in assertions] == ["interest.rust"]
    assert json.loads(assertions[0]["evidence_events"]) == ["rs-1", "rs-2", "rs-3"]


@pytest.mark.asyncio
async def test_rule_inferred_conflict_becomes_shadow(l2_store_with_schema):
    store = l2_store_with_schema
    await store.upsert_assertion_candidate(
        {
            "entity_id": "user:self",
            "entity_type": "user",
            "trait_family": "preference_profile",
            "trait_name": "interest.python",
            "trait_value": "JavaScript",
            "confidence_score": 0.8,
            "evidence_events": ["user-1"],
            "volatility_index": 0.2,
            "source_domain": "user_authored",
            "inference_depth": "topology_only",
            "validation_state": "tentative",
            "first_inferred_at": 1_710_000_000.0,
            "last_validated_at": 1_710_000_000.0,
            "target_entity_id": "topic:python",
            "target_entity_type": "topic",
            "target_scope": "entity_bound",
            "temporal_scope": "stable",
            "decay_policy": "evidence_only",
            "natural_summary": "User stated a preference for JavaScript",
        }
    )
    await _seed_edge(store, object_id="topic:python", event_ids=["py-1", "py-2", "py-3"])
    await _seed_canonical_name(store, entity_id="topic:python", canonical_name="Python")

    stats = await evaluate_graph_derived_assertion_rule(store, _interest_rule())

    assert stats["assertions_written"] == 1
    rows = await _assertions_for(store)
    active = [row for row in rows if row["status"] != "shadow"]
    shadow = [row for row in rows if row["status"] == "shadow"]
    assert [row["trait_value"] for row in active] == ["JavaScript"]
    assert [row["trait_value"] for row in shadow] == ["Python"]
