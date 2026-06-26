from __future__ import annotations

from typing import Any

from magi_plugin_sdk.sensors import SensorMemoryPolicy

from magi.awareness.sensor_projection import SensorProjection
from magi.events.domain_payloads import SensorEventEmitted, TaskContext


def make_sensor_event_payload(**overrides: Any) -> SensorEventEmitted:
    output_dict = {
        "source_type": "external_activity",
        "source_item_id": "win-app-foo-1234",
        "occurred_at": 1700.0,
        "captured_at": 1700.5,
        "domain_payload": {"app": "Chrome"},
        "raw_payload_ref": None,
        "provenance": {"hostname": "mac"},
        "tags": ["work"],
        "entities": [],
        "content_blocks": [],
    }
    base = dict(
        sensor_name="screen_time",
        payload=dict(output_dict),
        context=TaskContext(None, None, None, "user-1"),
        sensor_id="screen_time",
        output_dict=output_dict,
        metadata_dict={"entities": [], "tags": [], "relation_candidates": [], "fact_hints": []},
        policy_dict=SensorMemoryPolicy(
            memory_domain="external_activity",
            ingest_target="l1_only",
            cognition_eligible=True,
            tom_depth="none",
            retention_class="compressible",
            importance_bias=0.6,
            author_type="external",
            content_type="observation",
        ).to_dict(),
        projection_dict=SensorProjection(
            title="Used Chrome",
            summary="Used Chrome on Mac",
            content="Used Chrome on Mac",
            embedding_head="head",
            metadata={"projection_kind": "activity"},
        ).to_dict(),
        occurred_at=1700.0,
        owner_user_id="user-1",
        relation_candidates=(),
        allowed_edge_whitelist=(),
        sensor_fingerprint="fp-1",
        idempotency_key="sensor:screen_time:win-app-foo-1234:1700.0",
        memory_event_type="SENSOR_EVENT",
        l2_batch_policy_dict=None,
    )
    base.update(overrides)
    return SensorEventEmitted(**base)
