from __future__ import annotations

from typing import Any

from magi_plugin_sdk.sources import SourceMemoryPolicy

from magi.awareness.source_projection import SourceProjection
from magi.events.domain_payloads import SourceEventEmitted, TaskContext


def make_source_event_payload(**overrides: Any) -> SourceEventEmitted:
    output_dict = {
        "source_type": "external_activity",
        "source_item_id": "win-app-foo-1234",
        "occurred_at": 1700.0,
        "captured_at": 1700.5,
        "domain_payload": {"app": "Chrome", "source_id": "screen_time"},
        "raw_payload_ref": None,
        "provenance": {"hostname": "mac", "source_id": "screen_time"},
        "tags": ["work"],
        "entities": [],
        "content_blocks": [],
    }
    base = dict(
        source_name="screen_time",
        payload=dict(output_dict),
        context=TaskContext(None, None, None, "user-1"),
        source_id="screen_time",
        output_dict=output_dict,
        metadata_dict={"entities": [], "tags": [], "relation_candidates": [], "fact_hints": []},
        policy_dict=SourceMemoryPolicy(
            memory_domain="external_activity",
            ingest_target="l1_only",
            cognition_eligible=True,
            tom_depth="none",
            retention_class="compressible",
            importance_bias=0.6,
            author_type="external",
            content_type="observation",
        ).to_dict(),
        projection_dict=SourceProjection(
            title="Used Chrome",
            summary="Used Chrome on Mac",
            content="Used Chrome on Mac",
            embedding_head="head",
            metadata={"projection_kind": "activity", "source_id": "screen_time"},
        ).to_dict(),
        occurred_at=1700.0,
        owner_user_id="user-1",
        relation_candidates=(),
        allowed_edge_whitelist=(),
        source_fingerprint="fp-1",
        idempotency_key="source:screen_time:win-app-foo-1234:1700.0",
        memory_event_type="SOURCE_EVENT",
        l2_batch_policy_dict=None,
    )
    base.update(overrides)
    return SourceEventEmitted(**base)
