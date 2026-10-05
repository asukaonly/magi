"""Tests for event-scoped entity mention evidence."""

from types import SimpleNamespace

import pytest

from magi.memory.l2.pipeline.entities.resolution import L2EntityResolutionMixin


@pytest.mark.parametrize(
    ("mention", "texts", "expected"),
    [
        ("DIIV", ["昨晚去看了 DIIV 演出。", "今天修了项目。"], ["evt-0"]),
        ("DIIV", ["昨晚去看了演出。", "今天修了项目。"], []),
        ("group:diiv", ["我昨晚去看了它的演出。"], []),
    ],
)
def test_entity_mention_evidence_is_limited_to_events_with_matching_surface(
    mention, texts, expected
):
    events = [
        SimpleNamespace(event_id=f"evt-{index}", content=text) for index, text in enumerate(texts)
    ]
    assert (
        L2EntityResolutionMixin()._resolve_entity_mention_event_ids(
            mention_text=mention,
            normalized_surface="DIIV",
            evidence_events=events,
            fallback_event_ids=[event.event_id for event in events],
        )
        == expected
    )
