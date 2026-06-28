from __future__ import annotations

from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)
from magi.memory.l2.pipeline.extraction import build_l2_extraction_plan


def _event(
    event_id: str,
    *,
    author_type: str,
    content: str,
    memory_domain: MemoryDomain = MemoryDomain.INTERACTION,
    content_type: str = "text",
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id=event_id,
        timestamp=1710000000.0,
        created_at=1710000000.0,
        event_type="test",
        source="test",
        source_item_id=None,
        memory_domain=memory_domain,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.TOPOLOGY_ONLY,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id="s1",
        turn_id=None,
        user_id="u1",
        task_id=None,
        content=content,
        author_type=author_type,
        content_type=content_type,
        importance_score=0.5,
        level=20,
    )


def test_build_l2_extraction_plan_keeps_only_write_eligible_events() -> None:
    plan = build_l2_extraction_plan(
        [
            _event("evt-assistant", author_type="assistant", content="Sure."),
            _event("evt-self", author_type="user", content="I like black coffee."),
            _event("evt-question", author_type="user", content="What coffee is this?"),
            _event(
                "evt-external",
                author_type="external",
                content="Visited Manner Coffee.",
                memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
                content_type="observation",
            ),
        ]
    )

    assert [item.event.event_id for item in plan.decisions] == [
        "evt-assistant",
        "evt-self",
        "evt-question",
        "evt-external",
    ]
    assert [item.event.event_id for item in plan.eligible_decisions] == [
        "evt-self",
        "evt-external",
    ]
    assert plan.primary is not None
    assert plan.primary.event.event_id == "evt-external"
    assert plan.batch_event_ids == ["evt-self", "evt-external"]
    assert plan.skip_result is None


def test_build_l2_extraction_plan_describes_skip_result() -> None:
    plan = build_l2_extraction_plan(
        [_event("evt-assistant", author_type="assistant", content="Sounds good.")]
    )

    assert plan.primary is None
    assert plan.batch_event_ids == []
    assert plan.skip_result == {
        "relation_count": 0,
        "assertion_count": 0,
        "touched_entity_ids": [],
        "touched_place_ids": [],
        "touched_topic_keys": [],
        "skipped": True,
        "skip_reason": "assistant_freeform",
        "evidence_class": "assistant_freeform",
        "contradiction_hint_count": 0,
    }
