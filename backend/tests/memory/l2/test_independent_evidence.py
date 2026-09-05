"""Repeated ingestion and exposure retain lineage without becoming independent support."""

import json

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.evidence.independence import independent_evidence_key
from magi.memory.l2.assertions.derived_rules import _load_edge_evidence_stats


def test_reimports_and_tracking_urls_share_evidence_group():
    original = {"source": "history_import", "author_type": "user", "content": "我最近喜欢爵士乐", "event_id": "one"}
    assert independent_evidence_key(original) == independent_evidence_key({**original, "event_id": "two", "source_item_id": "new-batch"})
    article = {"source": "browser", "metadata_json": {"url": "https://example.com/article?id=1&utm_source=first"}}
    copy = {"source": "another-browser", "metadata_json": {"url": "https://example.com/article?utm_source=second&id=1#section"}}
    assert independent_evidence_key(article) == independent_evidence_key(copy)
    assert independent_evidence_key(article) != independent_evidence_key({"metadata_json": {"url": "https://example.com/article?id=2"}})


@pytest.mark.asyncio
async def test_repeated_article_visits_keep_lineage_but_one_support():
    class Source:
        async def get_evidence_records(self, ids):
            return {identity: {"event_id": identity, "source": "browser", "timestamp": 1000 + i * 86400, "metadata_json": {"url": "https://example.com/article"}} for i, identity in enumerate(ids)}
    result = await _load_edge_evidence_stats(edges=[{"triple_id": "edge", "object_id": "topic:music", "observation_count": 9, "evidence_event_ids": ["a", "b", "c"]}], l1_store=Source(), now=200000, canonical_names={"topic:music": "爵士乐"})
    assert result["edge"].evidence_count == 1
    assert result["edge"].observation_count == 9
    assert set(result["edge"].event_ids) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_assertion_reconcile_does_not_promote_copied_sources(l2_store_with_schema):
    store = l2_store_with_schema
    async def records(ids):
        return {identity: {"event_id": identity, "source": "history_import", "author_type": "user", "content": "相同的原始记录"} for identity in ids}
    store._evidence_record_resolver = records
    identity = await store.upsert_assertion_candidate({
        "entity_id": "user:test", "entity_type": "user", "trait_family": "interest_profile",
        "volatility_index": 0.4, "validation_state": "tentative",
        "trait_name": "interest.music", "trait_value": "爵士乐", "confidence_score": 0.3,
        "evidence_events": [f"copy{i}" for i in range(10)], "first_inferred_at": 1000,
        "last_validated_at": 1000000, "source_domain": "external_activity", "inference_depth": "topology_only",
    })
    assertion = await store.get_tom_assertion(assertion_id=identity)
    assert assertion["validation_state"] == "tentative"
    assert len(assertion["evidence_events"]) == 10
    await store.reconcile_entity(entity_id="user:test", entity_type="user")
    assertion = await store.get_tom_assertion(assertion_id=identity)
    assert assertion["validation_state"] == "tentative"
    assert assertion["confidence_score"] < 0.7
