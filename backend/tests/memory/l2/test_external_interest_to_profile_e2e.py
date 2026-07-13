"""External interest observations surface through graph-derived assertions."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

import pytest

from magi.events.events import EventLevel
from magi.memory.l2.assertions.interest_aggregation import aggregate_interests

from .test_pipeline import _FakeAdapter, _FakeScenarioPool, UnifiedMemoryStore


def _external_interest_phase1() -> str:
    return json.dumps(
        {
            "entities": [
                {
                    "surface": "rock climbing",
                    "normalized_name": "rock climbing",
                    "entity_type": "activity",
                    "specificity": "concrete",
                    "resolved_id": None,
                    "is_new": True,
                    "alias_signals": [],
                    "confidence": 0.9,
                }
            ],
            "fact_claims": [
                {
                    "subject_ref": "user:self",
                    "predicate": "INTERESTED_IN",
                    "object_ref": "rock climbing",
                    "object_type": "activity",
                    "fact_kind": "stable_preference",
                    "temporal_cue": "unspecified",
                    "polarity": "positive",
                    "specificity": "concrete",
                    "evidence_text": "browsed rock climbing gear reviews",
                    "confidence": 0.8,
                    "supporting_event_ids": ["evt-ext-interest-1"],
                }
            ],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "none"},
        }
    )


def _external_interest_phase2() -> str:
    return json.dumps(
        {
            "claim_assessments": [],
            "assertion_candidates": [],
        }
    )


async def _wait_for_relationships(store, *, entity_id: str, attempts: int = 300):
    rows: list = []
    for _ in range(attempts):
        rows = await store.l2.get_relationships(
            subject_id=entity_id,
            predicates=["INTERESTED_IN"],
            limit=50,
        )
        if rows:
            return rows
        await asyncio.sleep(0.02)
    return rows


@pytest.mark.asyncio
async def test_external_interest_surfaces_via_derived_preference_in_snapshot():
    adapter = _FakeAdapter([_external_interest_phase1(), _external_interest_phase2()])
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        store = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(adapter),
        )
        await store.initialize()
        try:
            ingest_result = await store.ingest_event(
                {
                    "id": "evt-ext-interest-1",
                    "type": "SENSOR_EVENT",
                    "timestamp": time.time(),
                    "source": "chrome_history",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "content": "browsed rock climbing gear reviews",
                        "author_type": "external",
                        "content_type": "observation",
                        "source_item_id": "web:evt-ext-interest-1",
                    },
                }
            )
            assert ingest_result["l1_written"] is True
            assert ingest_result["l2_job_enqueued"] is True

            relationships = await _wait_for_relationships(store, entity_id="user:u1")
            assert len(relationships) == 1, f"expected one graph edge, got {relationships!r}"
            assert relationships[0]["predicate"] == "INTERESTED_IN"
            first_edge = relationships[0]

            for index in range(2):
                await store.l2.upsert_knowledge_edge(
                    subject_id="user:u1",
                    subject_type="user",
                    predicate="INTERESTED_IN",
                    object_id=first_edge["object_id"],
                    object_type=first_edge["object_type"],
                    evidence_event_ids=[f"evt-ext-interest-extra-{index + 1}"],
                    confidence=0.7,
                    observed_at=time.time() + (index + 1) * 86_400,
                    source_type="chrome_history",
                )

            agg_stats = await aggregate_interests(
                store.l2,
                entity_id="user:u1",
                min_observations=3,
            )
            assert agg_stats["topics_aggregated"] == 1

            snapshot = await store.l2.refresh_entity_snapshot(
                entity_id="user:u1", entity_type="user"
            )
            assert snapshot is not None
            preferences = snapshot.get("preferences") or {}
            interest_keys = [key for key in preferences if key.startswith("interest.")]
            assert len(interest_keys) == 1, f"preference not in snapshot: {preferences!r}"
            pref = preferences[interest_keys[0]]
            assert pref["value"] == "rock climbing"
            assert pref["family"] == "preference_profile"
            assert pref["source_tier"] == "inferred"
        finally:
            await store.shutdown()
