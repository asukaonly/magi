from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.sources import SourceMemoryPolicy

from _shared.source_event_payloads import make_source_event_payload
from magi.awareness.source_projection import SourceProjection
from magi.memory.event_contracts import MemoryEvent
from magi.memory.source_event_projection import build_source_memory_event


def test_build_source_memory_event_carries_envelope_id() -> None:
    payload = make_source_event_payload()
    me = build_source_memory_event(
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
    assert me.event_type == "SOURCE_EVENT"
    assert me.source == "external_activity"
    assert me.source_item_id == "win-app-foo-1234"
    assert me.user_id == "user-1"
    assert me.idempotency_key == "source:screen_time:win-app-foo-1234:1700.0"


def test_build_source_memory_event_carries_pinned_payload_off_the_row() -> None:
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
    payload = make_source_event_payload(output_dict=out, payload=dict(out))
    me = build_source_memory_event(payload, event_id="evt-9")
    assert me.pinned_payload == "the full frozen note body, much longer than the summary"
    assert me.content == "Used Chrome on Mac"
    assert "pinned_payload" not in (me.metadata_json or {})


def test_build_source_memory_event_can_store_full_content_with_compact_timeline_summary() -> None:
    full_evidence_text = (
        "Magi AI Agent Framework 通知 对话 时间线 记忆 任务 设置 后台任务 "
        "调度配置 调度记录 今天 近 24 小时 近 7 天 全部 用户自定义 0 "
        "数据来源同步 5 记忆维护 1 时间线维护 0 状态 全部"
    )
    compact_summary = "Screenshot Timeline Screen Capture Magi: 调度记录"
    projection = SourceProjection(
        title="Screenshot Timeline Screen Capture · Magi: 调度记录",
        summary=compact_summary,
        content=f"Screenshot Timeline Screen Capture {full_evidence_text}",
        embedding_head="Screenshot Timeline Screen Capture",
        metadata={
            "projection": {
                "renderer_version": "source_activity_v1",
                "timeline_presentation": {"mode": "evidence_only"},
            }
        },
    )
    payload = make_source_event_payload(projection_dict=projection.to_dict())

    me = build_source_memory_event(payload, event_id="evt-evidence")

    assert me.content == f"Screenshot Timeline Screen Capture {full_evidence_text}"
    assert me.metadata_json["activity_snapshot"]["summary"] == compact_summary
    assert "timeline" not in me.metadata_json


def test_build_source_memory_event_threads_promotion_override() -> None:
    base = make_source_event_payload()
    me_default = build_source_memory_event(base, event_id="evt-d")
    assert "promotion_override" not in (me_default.metadata_json or {})

    out = dict(base.output_dict)
    out["promotion_override"] = "force_full"
    payload = make_source_event_payload(output_dict=out, payload=dict(out))
    me = build_source_memory_event(payload, event_id="evt-f")
    assert me.metadata_json["promotion_override"] == "force_full"


def test_build_source_memory_event_metadata_carries_activity_snapshot() -> None:
    payload = make_source_event_payload()
    me = build_source_memory_event(payload, event_id="evt-1")
    assert "activity_snapshot" in (me.metadata_json or {})
    assert "timeline" not in (me.metadata_json or {})
    assert me.metadata_json["activity_snapshot"]["event_id"] == "evt-1"
    assert me.metadata_json["memory_owner_user_id"] == "user-1"


def test_build_source_memory_event_with_l2_batch_policy() -> None:
    payload = make_source_event_payload(l2_batch_policy_dict={
        "owner": "screen_time",
        "catch_up_owner": "screen_time",
        "max_events": 50,
        "min_ready_events": 10,
        "max_estimated_tokens": 8000,
        "max_wait_seconds": 60,
    })
    me = build_source_memory_event(payload, event_id="evt-2")
    assert me.metadata_json["l2_batch_owner"] == "screen_time"
    assert me.metadata_json["l2_batch_max_events"] == 50
    assert me.metadata_json["l2_batch_max_wait_seconds"] == 60


def test_build_source_memory_event_with_relation_hints() -> None:
    payload = make_source_event_payload(
        metadata_dict={
            "entities": [{"id": "e1", "type": "topic"}],
            "tags": ["x"],
            "fact_hints": [{"predicate": "uses", "object_id": "tool:chrome"}],
            "relation_candidates": [],
        },
    )
    me = build_source_memory_event(payload, event_id="evt-3")
    assert me.metadata_json["structured_entity_hints"] == [{"id": "e1", "type": "topic"}]
    assert me.metadata_json["structured_graph_hints"] == [{"predicate": "uses", "object_id": "tool:chrome"}]


def test_default_memory_event_type_when_missing() -> None:
    payload = make_source_event_payload(memory_event_type="")
    me = build_source_memory_event(payload, event_id="evt-4")
    assert me.event_type == "SOURCE_EVENT"


def test_structured_only_flag_threaded_into_metadata_when_disabled() -> None:
    payload = make_source_event_payload(
        policy_dict=SourceMemoryPolicy(
            cognition_eligible=True, allow_llm_extraction=False
        ).to_dict(),
    )
    me = build_source_memory_event(payload, event_id="evt-so")
    assert me.metadata_json["allow_llm_extraction"] is False


def test_structured_only_flag_absent_by_default() -> None:
    payload = make_source_event_payload()
    me = build_source_memory_event(payload, event_id="evt-def")
    assert "allow_llm_extraction" not in (me.metadata_json or {})


@pytest.mark.asyncio
async def test_source_identity_survives_l1_and_timeline_round_trip(tmp_path: Path) -> None:
    from magi.memory.l1.event_store import L1EventStore
    from magi.timeline.contracts import TimelineEvent
    from magi.timeline.source_event_projection import build_timeline_event_dict

    store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await store.initialize()
    try:
        for connection_id in ("account-personal", "account-work"):
            source_identity = {
                "source_id": "timeline.calendar",
                "source_connection_id": connection_id,
                "source_object_id": "meeting-7",
                "source_object_version": "revision-3",
            }
            base = make_source_event_payload()
            output = dict(base.output_dict)
            output.update(
                source_type="calendar_event",
                source_item_id=f"{connection_id}:meeting-7",
                domain_payload=dict(source_identity),
                provenance=dict(source_identity),
            )
            projection = dict(base.projection_dict)
            projection["metadata"] = {"source_id": "timeline.calendar"}
            payload = make_source_event_payload(
                source_name="timeline.calendar",
                source_id="timeline.calendar",
                output_dict=output,
                payload=dict(output),
                projection_dict=projection,
                idempotency_key=f"{connection_id}:meeting-7:revision-3",
            )
            event_id = f"event-{connection_id}"
            event = build_source_memory_event(payload, event_id=event_id)
            await store.store(event)
            stored = await store.get_event(event_id)
            assert stored is not None
            assert stored["source"] == "calendar_event"
            assert stored["source_item_id"] == f"{connection_id}:meeting-7"
            assert stored["metadata_json"]["source_id"] == "timeline.calendar"
            assert stored["metadata_json"]["source_connection_id"] == connection_id
            snapshot = stored["metadata_json"]["activity_snapshot"]
            assert snapshot["provenance"] == source_identity
            timeline = TimelineEvent.from_dict(
                build_timeline_event_dict(payload, event_id=event_id)
            )
            assert timeline.provenance == source_identity
            assert timeline.source_type == "calendar_event"
            assert timeline.source_item_id == stored["source_item_id"]
        assert await store.count_events() == 2
    finally:
        await store.shutdown()
