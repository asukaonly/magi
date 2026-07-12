"""Tests for event-scoped entity mention evidence."""

from types import SimpleNamespace

from magi.memory.l2.pipeline.entities.resolution import L2EntityResolutionMixin


def test_entity_mention_does_not_fall_back_to_whole_batch() -> None:
    resolver = L2EntityResolutionMixin()

    event_ids = resolver._resolve_entity_mention_event_ids(
        mention_text="DIIV",
        normalized_surface="DIIV",
        evidence_events=[
            SimpleNamespace(event_id="evt-a", content="昨晚去看了演出。"),
            SimpleNamespace(event_id="evt-b", content="今天修了项目。"),
        ],
        fallback_event_ids=["evt-a", "evt-b"],
    )

    assert event_ids == []


def test_entity_mention_uses_only_matching_events() -> None:
    resolver = L2EntityResolutionMixin()

    event_ids = resolver._resolve_entity_mention_event_ids(
        mention_text="DIIV",
        normalized_surface="DIIV",
        evidence_events=[
            SimpleNamespace(event_id="evt-a", content="昨晚去看了 DIIV 演出。"),
            SimpleNamespace(event_id="evt-b", content="今天修了项目。"),
        ],
        fallback_event_ids=["evt-a", "evt-b"],
    )

    assert event_ids == ["evt-a"]


def test_entity_mention_single_event_is_an_exact_fallback() -> None:
    resolver = L2EntityResolutionMixin()

    event_ids = resolver._resolve_entity_mention_event_ids(
        mention_text="group:diiv",
        normalized_surface="DIIV",
        evidence_events=[SimpleNamespace(event_id="evt-only", content="我昨晚去看了它的演出。")],
        fallback_event_ids=["evt-only"],
    )

    assert event_ids == ["evt-only"]
