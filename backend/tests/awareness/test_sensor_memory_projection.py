"""Phase 2 of C: pure projection functions for sensor → MemoryEvent / TimelineEvent dict."""
from __future__ import annotations

from typing import Any

from magi_plugin_sdk.sensors import SensorMemoryPolicy

from magi.awareness.sensor_projection import SensorProjection
from magi.awareness.sensor_memory_projection import (
    build_sensor_memory_event,
    build_timeline_event_dict,
)
from magi.events.domain_payloads import SensorEventEmitted, TaskContext
from magi.memory.event_contracts import MemoryEvent


def _make_payload(**overrides: Any) -> SensorEventEmitted:
    """Build a SensorEventEmitted with the C-extended payload shape."""
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


def test_build_timeline_event_dict_has_required_keys():
    payload = _make_payload()
    d = build_timeline_event_dict(payload, event_id="evt-1")
    assert d["event_id"] == "evt-1"
    assert d["source_type"] == "external_activity"
    assert d["source_item_id"] == "win-app-foo-1234"
    assert d["title"] == "Used Chrome"
    assert d["summary"] == "Used Chrome on Mac"


def test_build_sensor_memory_event_carries_envelope_id():
    payload = _make_payload()
    me = build_sensor_memory_event(
        payload,
        event_id="evt-7",
        correlation_id="corr-7",
        causation_id="parent-7",
        trace_context=None,
    )
    assert isinstance(me, MemoryEvent)
    assert me.event_id == "evt-7"
    assert me.correlation_id == "corr-7"
    assert me.causation_id == "parent-7"
    assert me.event_type == "SENSOR_EVENT"
    assert me.source == "external_activity"
    assert me.source_item_id == "win-app-foo-1234"
    assert me.user_id == "user-1"
    assert me.idempotency_key == "sensor:screen_time:win-app-foo-1234:1700.0"


def test_build_sensor_memory_event_carries_pinned_payload_off_the_row():
    # RFC #56 P3: a sensor pins the capture-time full text; it must reach the
    # MemoryEvent as a transient field (-> L1 satellite) WITHOUT bloating the
    # persisted row (content stays the lean summary; metadata_json excludes it).
    out = {
        "source_type": "obsidian_vault",
        "source_item_id": "note-1",
        "occurred_at": 1700.0,
        "captured_at": 1700.5,
        "domain_payload": {},
        "raw_payload_ref": None,
        "pinned_payload": "the full frozen note body, much longer than the summary",
        "provenance": {},
        "tags": [],
        "entities": [],
        "content_blocks": [],
    }
    payload = _make_payload(output_dict=out, payload=dict(out))
    me = build_sensor_memory_event(payload, event_id="evt-9")
    assert me.pinned_payload == "the full frozen note body, much longer than the summary"
    assert me.content == "Used Chrome on Mac"  # lean summary, not the full body
    assert "pinned_payload" not in (me.metadata_json or {})


def test_build_sensor_memory_event_can_store_full_content_with_compact_timeline_summary():
    full_evidence_text = (
        "Magi AI Agent Framework 通知 对话 时间线 记忆 任务 设置 后台任务 "
        "调度配置 调度记录 今天 近 24 小时 近 7 天 全部 用户自定义 0 "
        "传感器同步 5 记忆维护 1 时间线维护 0 状态 全部"
    )
    compact_summary = "Screenshot Timeline Screen Capture Magi: 调度记录"
    projection = SensorProjection(
        title="Screenshot Timeline Screen Capture · Magi: 调度记录",
        summary=compact_summary,
        content=f"Screenshot Timeline Screen Capture {full_evidence_text}",
        embedding_head="Screenshot Timeline Screen Capture",
        metadata={
            "projection": {
                "renderer_version": "sensor_activity_v1",
                "timeline_presentation": {"mode": "evidence_only"},
            }
        },
    )
    payload = _make_payload(projection_dict=projection.to_dict())

    me = build_sensor_memory_event(payload, event_id="evt-evidence")

    assert me.content == f"Screenshot Timeline Screen Capture {full_evidence_text}"
    assert me.metadata_json["timeline"]["summary"] == compact_summary


def test_build_sensor_memory_event_threads_promotion_override():
    # RFC #56 P4: a per-event promotion override flows into metadata_json so
    # resolve_llm_extraction can honor it. Stored only when set (lean otherwise).
    base = _make_payload()
    me_default = build_sensor_memory_event(base, event_id="evt-d")
    assert "promotion_override" not in (me_default.metadata_json or {})

    out = dict(base.output_dict)
    out["promotion_override"] = "force_full"
    payload = _make_payload(output_dict=out, payload=dict(out))
    me = build_sensor_memory_event(payload, event_id="evt-f")
    assert me.metadata_json["promotion_override"] == "force_full"


def test_build_sensor_memory_event_metadata_carries_timeline_dict():
    payload = _make_payload()
    me = build_sensor_memory_event(payload, event_id="evt-1")
    assert "timeline" in (me.metadata_json or {})
    assert me.metadata_json["timeline"]["event_id"] == "evt-1"
    assert me.metadata_json["memory_owner_user_id"] == "user-1"


def test_build_sensor_memory_event_with_l2_batch_policy():
    payload = _make_payload(l2_batch_policy_dict={
        "owner": "screen_time",
        "catch_up_owner": "screen_time",
        "max_events": 50,
        "min_ready_events": 10,
        "max_estimated_tokens": 8000,
        "max_wait_seconds": 60,
    })
    me = build_sensor_memory_event(payload, event_id="evt-2")
    assert me.metadata_json["l2_batch_owner"] == "screen_time"
    assert me.metadata_json["l2_batch_max_events"] == 50
    assert me.metadata_json["l2_batch_max_wait_seconds"] == 60


def test_build_sensor_memory_event_with_relation_hints():
    payload = _make_payload(
        metadata_dict={
            "entities": [{"id": "e1", "type": "topic"}],
            "tags": ["x"],
            "fact_hints": [{"predicate": "uses", "object_id": "tool:chrome"}],
            "relation_candidates": [],
        },
    )
    me = build_sensor_memory_event(payload, event_id="evt-3")
    assert me.metadata_json["structured_entity_hints"] == [{"id": "e1", "type": "topic"}]
    assert me.metadata_json["structured_graph_hints"] == [{"predicate": "uses", "object_id": "tool:chrome"}]


def test_default_memory_event_type_when_missing():
    payload = _make_payload(memory_event_type="")
    me = build_sensor_memory_event(payload, event_id="evt-4")
    assert me.event_type == "SENSOR_EVENT"


def test_structured_only_flag_threaded_into_metadata_when_disabled():
    # A sensor declaring allow_llm_extraction=False (structured-only) must surface in
    # metadata_json so L2 can do deterministic direct-writes but skip the LLM.
    payload = _make_payload(
        policy_dict=SensorMemoryPolicy(
            cognition_eligible=True, allow_llm_extraction=False
        ).to_dict(),
    )
    me = build_sensor_memory_event(payload, event_id="evt-so")
    assert me.metadata_json["allow_llm_extraction"] is False


def test_structured_only_flag_absent_by_default():
    # Lean metadata: only stored when False. Extraction treats a missing key as True.
    payload = _make_payload()
    me = build_sensor_memory_event(payload, event_id="evt-def")
    assert "allow_llm_extraction" not in (me.metadata_json or {})
