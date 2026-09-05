"""Tests for graph-derived assertion rules."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.identity.defaults import CANONICAL_LOCAL_USER
from magi.memory.l2.assertions.derived_rules import (
    GraphDerivedAssertionRule,
    evaluate_graph_derived_assertion_rule,
)


DEFAULT_USER_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


class _EvidenceEventStore:
    def __init__(
        self,
        timestamps: dict[str, float] | None = None,
        *,
        spread_days: bool = True,
    ) -> None:
        self.timestamps = timestamps
        self.spread_days = spread_days

    async def get_event_timestamps(self, event_ids: list[str]) -> dict[str, float]:
        if self.timestamps is None:
            unique_ids = sorted(set(event_ids))
            latest = time.time()
            interval = 86_400 if self.spread_days else 0.001
            return {
                event_id: latest - (len(unique_ids) - index - 1) * interval
                for index, event_id in enumerate(unique_ids)
            }
        return {
            event_id: self.timestamps[event_id]
            for event_id in event_ids
            if event_id in self.timestamps
        }

    async def get_evidence_records(self, event_ids: list[str]) -> dict[str, dict]:
        return {event_id: {"event_id": event_id, "timestamp": timestamp, "source": "test", "metadata_json": {}} for event_id, timestamp in (await self.get_event_timestamps(event_ids)).items()}


async def _seed_edge(
    store: Any,
    *,
    object_id: str,
    event_ids: list[str],
    predicate: str = "INTERESTED_IN",
    object_type: str = "topic",
    source_type: str = "chrome_history",
    entity_id: str = DEFAULT_USER_ENTITY_ID,
    confidence: float = 0.8,
    observed_interval_seconds: float = 0.001,
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
            observed_at=now + index * observed_interval_seconds,
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


async def _assertions_for(store: Any, *, entity_id: str = DEFAULT_USER_ENTITY_ID) -> list[dict[str, Any]]:
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
        trait_family="interest_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=min_observations,
        min_distinct_days=2,
        source_domains=("external_activity",),
        value_strategy="canonical_name",
    )


def _topic_only_interest_rule(*, min_observations: int = 3) -> GraphDerivedAssertionRule:
    return GraphDerivedAssertionRule(
        rule_id="browser.topic_interest",
        source_predicates=("INTERESTED_IN",),
        trait_family="interest_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=min_observations,
        min_distinct_days=2,
        source_domains=("external_activity",),
        value_strategy="canonical_name",
        object_types=("topic", "media"),
    )


@pytest.mark.asyncio
async def test_rule_filters_by_observation_threshold(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(store, object_id="topic:python", event_ids=["py-1", "py-2", "py-3"])
    await _seed_canonical_name(store, entity_id="topic:python", canonical_name="Python")
    await _seed_edge(store, object_id="topic:fortran", event_ids=["ft-1", "ft-2"])
    await _seed_canonical_name(store, entity_id="topic:fortran", canonical_name="Fortran")

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=_EvidenceEventStore(),
    )

    assert stats["edges_seen"] == 2
    assert stats["assertions_written"] == 1
    assertions = await _assertions_for(store)
    assert [item["trait_name"] for item in assertions] == ["interest.python"]
    assert assertions[0]["trait_value"] == "Python"
    assert assertions[0]["source_domain"] == "external_activity"


@pytest.mark.asyncio
async def test_rule_filters_by_object_type(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(
        store,
        object_id="software:github",
        object_type="software",
        predicate="INTERESTED_IN",
        event_ids=["gh-1", "gh-2", "gh-3"],
    )
    await _seed_canonical_name(
        store,
        entity_id="software:github",
        canonical_name="GitHub",
        entity_type="software",
    )
    await _seed_edge(
        store,
        object_id="topic:memory-systems",
        object_type="topic",
        predicate="INTERESTED_IN",
        event_ids=["mem-1", "mem-2", "mem-3"],
    )
    await _seed_canonical_name(
        store,
        entity_id="topic:memory-systems",
        canonical_name="Memory systems",
        entity_type="topic",
    )

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        _topic_only_interest_rule(),
        l1_store=_EvidenceEventStore(),
    )

    assert stats["edges_seen"] == 2
    assert stats["assertions_written"] == 1
    assertions = await _assertions_for(store)
    assert [item["trait_name"] for item in assertions] == ["interest.memory-systems"]


@pytest.mark.asyncio
async def test_rule_skips_low_quality_profile_values(l2_store_with_schema):
    store = l2_store_with_schema
    low_quality_objects = [
        ("topic:https://example.com/articles/123?utm_source=feed", "https://example.com/articles/123?utm_source=feed"),
        ("topic:/Users/asuka/code/magi/backend/run_server.py", "/Users/asuka/code/magi/backend/run_server.py"),
        ("topic:30.123456,120.654321", "30.123456,120.654321"),
        ("topic:69ebe866b62c4f6db421b9f3de4d3fd3", "69ebe866b62c4f6db421b9f3de4d3fd3"),
    ]
    for index, (object_id, canonical_name) in enumerate(low_quality_objects):
        await _seed_edge(
            store,
            object_id=object_id,
            event_ids=[f"noise-{index}-1", f"noise-{index}-2", f"noise-{index}-3"],
        )
        await _seed_canonical_name(store, entity_id=object_id, canonical_name=canonical_name)

    await _seed_edge(
        store,
        object_id="topic:memory-systems",
        event_ids=["mem-1", "mem-2", "mem-3"],
    )
    await _seed_canonical_name(store, entity_id="topic:memory-systems", canonical_name="Memory systems")

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=_EvidenceEventStore(),
    )

    assert stats["edges_seen"] == 5
    assert stats["assertions_written"] == 1
    assertions = await _assertions_for(store)
    assert [item["trait_name"] for item in assertions] == ["interest.memory-systems"]


@pytest.mark.asyncio
async def test_rule_keeps_version_like_profile_values(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(
        store,
        object_id="topic:gpt-5.5",
        event_ids=["gpt-1", "gpt-2", "gpt-3"],
    )
    await _seed_canonical_name(store, entity_id="topic:gpt-5.5", canonical_name="GPT-5.5")

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=_EvidenceEventStore(),
    )

    assert stats["assertions_written"] == 1
    assertions = await _assertions_for(store)
    assert [item["trait_value"] for item in assertions] == ["GPT-5.5"]


@pytest.mark.asyncio
async def test_rule_is_idempotent(l2_store_with_schema):
    store = l2_store_with_schema
    await _seed_edge(store, object_id="topic:rust", event_ids=["rs-1", "rs-2", "rs-3"])
    await _seed_canonical_name(store, entity_id="topic:rust", canonical_name="Rust")

    l1_store = _EvidenceEventStore()
    first = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=l1_store,
    )
    second = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=l1_store,
    )

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
            "entity_id": DEFAULT_USER_ENTITY_ID,
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

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=_EvidenceEventStore(),
    )

    assert stats["assertions_written"] == 1
    rows = await _assertions_for(store)
    active = [row for row in rows if row["status"] != "shadow"]
    shadow = [row for row in rows if row["status"] == "shadow"]
    assert [row["trait_value"] for row in active] == ["JavaScript"]
    assert [row["trait_value"] for row in shadow] == ["Python"]


@pytest.mark.asyncio
async def test_rule_uses_l1_evidence_times_for_recent_promotion(l2_store_with_schema):
    store = l2_store_with_schema
    now = time.time()
    event_ids = ["diiv-1", "diiv-2", "diiv-3"]
    await _seed_edge(store, object_id="group:diiv", event_ids=event_ids)
    await _seed_canonical_name(
        store,
        entity_id="group:diiv",
        canonical_name="DIIV",
        entity_type="group",
    )
    l1_store = _EvidenceEventStore(
        {
            "diiv-1": now - 3 * 86_400,
            "diiv-2": now - 2 * 86_400,
            "diiv-3": now - 1 * 86_400,
        }
    )
    rule = GraphDerivedAssertionRule(
        rule_id="music.recent-interest",
        source_predicates=("INTERESTED_IN",),
        trait_family="interest_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=3,
        min_distinct_days=2,
        signal_preset="passive_exposure",
        source_domains=("external_activity",),
    )

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        rule,
        l1_store=l1_store,
        now=now,
    )

    assert stats["assertions_written"] == 1
    row = (await _assertions_for(store))[0]
    assert row["trait_family"] == "interest_profile"
    assert row["temporal_scope"] == "recent"
    assert row["expires_at"] == pytest.approx(now - 86_400 + 14 * 86_400)


@pytest.mark.asyncio
async def test_rule_requires_exact_l1_distinct_days_not_graph_span(l2_store_with_schema):
    store = l2_store_with_schema
    now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
    event_ids = ["same-day-1", "same-day-2", "same-day-3"]
    await _seed_edge(
        store,
        object_id="topic:one-task",
        event_ids=event_ids,
        observed_interval_seconds=86_400,
    )
    l1_store = _EvidenceEventStore(
        {
            "same-day-1": now - 3_600,
            "same-day-2": now - 1_800,
            "same-day-3": now - 60,
        }
    )
    rule = GraphDerivedAssertionRule(
        rule_id="browser.recent-interest",
        source_predicates=("INTERESTED_IN",),
        trait_family="interest_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=3,
        min_distinct_days=2,
        signal_preset="passive_exposure",
    )

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        rule,
        l1_store=l1_store,
        now=now,
    )

    assert stats["assertions_written"] == 0
    assert await _assertions_for(store) == []


@pytest.mark.asyncio
async def test_rule_promotes_sustained_engagement_only_with_durable_gates(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    event_ids = [f"project-{index}" for index in range(8)]
    await _seed_edge(
        store,
        object_id="project:magi",
        object_type="project",
        predicate="CONTRIBUTES_TO",
        source_type="coding_agent_history",
        event_ids=event_ids,
    )
    await _seed_canonical_name(
        store,
        entity_id="project:magi",
        canonical_name="Magi",
        entity_type="project",
    )
    l1_store = _EvidenceEventStore(
        {
            event_id: now - (35 - index * 5) * 86_400
            for index, event_id in enumerate(event_ids)
        }
    )
    rule = GraphDerivedAssertionRule(
        rule_id="coding.project",
        source_predicates=("CONTRIBUTES_TO",),
        trait_family="project_profile",
        trait_name_template="project.{object_slug}",
        min_observations=2,
        min_distinct_days=2,
        signal_preset="sustained_engagement",
        durable_permitted=True,
        durable_min_observations=6,
        durable_min_distinct_days=3,
        durable_min_span_days=14,
        source_types=("coding_agent_history",),
    )

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        rule,
        l1_store=l1_store,
        now=now,
    )

    assert stats["assertions_written"] == 1
    row = (await _assertions_for(store))[0]
    assert row["trait_family"] == "project_profile"
    assert row["temporal_scope"] == "stable"
    assert row["expires_at"] is None


@pytest.mark.asyncio
async def test_rule_upgrades_recent_assertion_to_durable_in_place(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    recent_event_ids = ["magi-recent-1", "magi-recent-2", "magi-recent-3"]
    await _seed_edge(
        store,
        object_id="project:magi",
        object_type="project",
        predicate="CONTRIBUTES_TO",
        source_type="coding_agent_history",
        event_ids=recent_event_ids,
    )
    await _seed_canonical_name(
        store,
        entity_id="project:magi",
        canonical_name="Magi",
        entity_type="project",
    )
    timestamps = {
        "magi-recent-1": now - 3 * 86_400,
        "magi-recent-2": now - 2 * 86_400,
        "magi-recent-3": now - 86_400,
    }
    l1_store = _EvidenceEventStore(timestamps)
    rule = GraphDerivedAssertionRule(
        rule_id="coding.project",
        source_predicates=("CONTRIBUTES_TO",),
        trait_family="project_profile",
        trait_name_template="project.{object_slug}",
        min_observations=2,
        min_distinct_days=2,
        signal_preset="sustained_engagement",
        durable_permitted=True,
        durable_min_observations=6,
        durable_min_distinct_days=3,
        durable_min_span_days=14,
        source_types=("coding_agent_history",),
    )

    await evaluate_graph_derived_assertion_rule(
        store,
        rule,
        l1_store=l1_store,
        now=now,
    )
    recent_row = (await _assertions_for(store))[0]
    assert recent_row["temporal_scope"] == "recent"
    assert recent_row["expires_at"] is not None

    older_event_ids = ["magi-older-1", "magi-older-2", "magi-older-3"]
    await _seed_edge(
        store,
        object_id="project:magi",
        object_type="project",
        predicate="CONTRIBUTES_TO",
        source_type="coding_agent_history",
        event_ids=older_event_ids,
    )
    timestamps.update(
        {
            "magi-older-1": now - 24 * 86_400,
            "magi-older-2": now - 18 * 86_400,
            "magi-older-3": now - 12 * 86_400,
        }
    )

    await evaluate_graph_derived_assertion_rule(
        store,
        rule,
        l1_store=l1_store,
        now=now,
    )

    rows = await _assertions_for(store)
    assert len(rows) == 1
    assert rows[0]["assertion_id"] == recent_row["assertion_id"]
    assert rows[0]["temporal_scope"] == "stable"
    assert rows[0]["expires_at"] is None


@pytest.mark.asyncio
async def test_rule_does_not_create_already_expired_recent_assertion(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    now = time.time()
    event_ids = ["old-1", "old-2", "old-3"]
    await _seed_edge(store, object_id="topic:old-interest", event_ids=event_ids)
    l1_store = _EvidenceEventStore(
        {
            "old-1": now - 40 * 86_400,
            "old-2": now - 30 * 86_400,
            "old-3": now - 20 * 86_400,
        }
    )

    stats = await evaluate_graph_derived_assertion_rule(
        store,
        _interest_rule(),
        l1_store=l1_store,
        now=now,
    )

    assert stats["assertions_written"] == 0
    assert await _assertions_for(store) == []
