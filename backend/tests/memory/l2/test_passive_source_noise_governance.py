"""Tests for P1-B3: passive source noise governance, batching, cooldowns, and KG bypass closure."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import pytest

from _shared.memory_stores import build_memory_store
from magi.events.domain_payloads import SourceEventEmitted, TaskContext
from magi.events.events import EventLevel
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l2.extraction_profiles import resolve_extraction_profile
from magi.memory.l2.promotion_counter import L2PromotionCounter
from magi.memory.source_event_projection import build_source_memory_event


@pytest.mark.asyncio
async def test_50_same_domain_chrome_events_trigger_at_most_two_full_extractions(tmp_path) -> None:
    counter = L2PromotionCounter(str(tmp_path / "promo.db"))
    await counter.initialize()
    base = 1_750_000_000.0
    admitted = 0
    for idx in range(50):
        # 50 events spread across 10 minutes (12s apart) for the same noisy domain
        count, llm_ok = await counter.bump(
            "chrome_history",
            "github.com",
            f"evt-chrome-{idx}",
            threshold=3,
            now=base + idx * 12.0,
        )
        assert count == idx + 1
        if llm_ok:
            admitted += 1

    assert admitted <= 2
    assert admitted == 1

    # Inactive promoted key decays after 90 days TTL during prune_stale.
    pruned_early = await counter.prune_stale(
        retention_seconds=7 * 86400.0,
        now=base + 30 * 86400.0,
    )
    assert pruned_early == 0

    pruned_expired = await counter.prune_stale(
        retention_seconds=7 * 86400.0,
        now=base + 95 * 86400.0,
    )
    assert pruned_expired == 1


@pytest.mark.asyncio
async def test_20_sessionless_external_events_aggregate_into_source_hour_batches(tmp_path) -> None:
    store = build_memory_store(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=60,
    )
    await store.initialize()
    try:
        base_hour = float((int(time.time()) // 3600) * 3600 + 100)
        for idx in range(20):
            event = MemoryEvent(
                event_id=f"ext-batch-{idx}",
                correlation_id=f"corr-ext-{idx}",
                timestamp=base_hour + idx * 10.0,
                created_at=base_hour + idx * 10.0,
                event_type="WEB_VISIT",
                source="chrome_history",
                source_item_id=f"chrome-item-{idx}",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.TOPOLOGY_ONLY,
                retention_class=RetentionClass.COMPRESSIBLE,
                session_id=None,
                turn_id=None,
                user_id="u-batch",
                task_id=None,
                content=f"Visited docs page {idx}",
                author_type="external",
                content_type="observation",
                importance_score=0.5,
                level=EventLevel.INFO.value,
                metadata_json=None,
            )
            await store.ingest_event(event)

        with sqlite3.connect(store.memory_db_path) as conn:
            owners = conn.execute(
                "SELECT DISTINCT batch_owner FROM l2_projection_jobs WHERE source = 'chrome_history'"
            ).fetchall()
            counts = conn.execute(
                "SELECT COUNT(*), MIN(max_events) FROM l2_projection_jobs WHERE source = 'chrome_history'"
            ).fetchone()

        assert counts is not None
        assert counts[0] == 20
        assert counts[1] == 12
        # All 20 events share a single source+hour batch_owner (<= 2 batches at max_events=12).
        assert len(owners) == 1
        assert owners[0][0] == f"source:chrome_history:{int(base_hour // 3600)}"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_relation_candidates_blocked_by_source_default_profile_and_forgetting(tmp_path) -> None:
    payload = SourceEventEmitted(
        source_name="untrusted_rss",
        payload={},
        context=TaskContext(None, None, None, "u1"),
        source_id="rss.feed",
        owner_user_id="u1",
        output_dict={
            "source_type": "untrusted_rss",
            "source_item_id": "rss-1",
            "occurred_at": time.time(),
            "captured_at": time.time(),
        },
        projection_dict={"summary": "Read an article about SQLite"},
        policy_dict={
            "memory_domain": "external_activity",
            "ingest_target": "l1_only",
            "cognition_eligible": True,
            "tom_depth": "topology_only",
        },
        relation_candidates=(
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_id": "topic:crypto_scam",
                "object_type": "topic",
                "confidence": 0.99,
            },
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "USES",
                "object_id": "software:sqlite",
                "object_type": "software",
                "confidence": 0.9,
            },
        ),
        allowed_edge_whitelist=("LIKES", "USES"),
        occurred_at=time.time(),
    )
    event = build_source_memory_event(payload, event_id="evt-rss-1")
    profile = resolve_extraction_profile(event)
    assert profile.profile_id == "source.default"
    assert "LIKES" not in profile.effective_structured_allowed_predicates
    assert "USES" in profile.effective_structured_allowed_predicates

    store = build_memory_store(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=False,
        enable_l4=False,
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    try:
        # Mark event structured-only so no LLM is required, testing deterministic L2 structured_graph_hints governance.
        assert event.metadata_json is not None
        event.metadata_json["allow_llm_extraction"] = False

        await store.ingest_event(event)
        for _ in range(300):
            if store.get_l2_pipeline_stats()["extract_completed"] >= 1:
                break
            await asyncio.sleep(0.01)

        edges = await store.l2.get_relationships(subject_id="user:u1") if store.l2 else []
        predicates = {(edge["predicate"], edge["object_id"]) for edge in edges}
        # Unauthorized LIKES predicate is blocked by source.default profile; valid USES edge passes.
        assert ("LIKES", "topic:crypto_scam") not in predicates
        assert ("USES", "software:sqlite") in predicates

        # Now forget the source event -> derived graph edge is purged and cannot reappear.
        assert await store.forget_source_event("evt-rss-1") is True
        edges_after = await store.l2.get_relationships(subject_id="user:u1") if store.l2 else []
        assert not any(edge["object_id"] == "software:sqlite" for edge in edges_after)
    finally:
        await store.shutdown()
