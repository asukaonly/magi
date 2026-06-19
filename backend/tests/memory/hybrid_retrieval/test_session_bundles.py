from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.memory.hybrid_retrieval.evidence.session_bundles import EvidenceBundleMixin


class _SessionEventStore:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    async def query_events(self, *, session_id: str, limit: int = 100, **kwargs: Any) -> list[dict[str, Any]]:
        _ = kwargs
        return [event for event in self.events if event.get("session_id") == session_id][:limit]


class _EvidenceBundleHost(EvidenceBundleMixin):
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._memory = SimpleNamespace(l1=_SessionEventStore(events))
        self._config = SimpleNamespace(
            evidence_bundle_min_score=0.0,
            evidence_bundle_max_count=8,
        )


@pytest.mark.asyncio
async def test_evidence_bundle_expands_neighbors_by_session_sequence() -> None:
    events = [
        {
            "event_id": f"evt-{index}",
            "session_id": "session-seq",
            "turn_id": f"turn_{index}",
            "session_seq": index,
            "timestamp": float(index),
            "content": f"message {index}",
            "retrieval_score": 0.1,
        }
        for index in range(20)
    ]
    hit = dict(events[10])
    hit["retrieval_score"] = 0.9

    bundles = await _EvidenceBundleHost(events)._build_l1_evidence_bundles([hit], query="message")

    assert len(bundles) == 1
    assert [event["event_id"] for event in bundles[0]["events"]] == [
        f"evt-{index}" for index in range(5, 16)
    ]
    assert bundles[0]["neighbor_expansion_applied"] is True


@pytest.mark.asyncio
async def test_evidence_bundle_does_not_expand_turn_id_neighbors_without_session_sequence() -> None:
    events = [
        {
            "event_id": f"evt-{index}",
            "session_id": "session-locomo",
            "turn_id": f"D1:{index}",
            "timestamp": float(index),
            "content": f"message {index}",
            "retrieval_score": 0.1,
        }
        for index in range(20)
    ]
    hit = dict(events[10])
    hit["retrieval_score"] = 0.9

    bundles = await _EvidenceBundleHost(events)._build_l1_evidence_bundles([hit], query="message")

    assert [event["event_id"] for event in bundles[0]["events"]] == ["evt-10"]
    assert bundles[0]["neighbor_expansion_applied"] is False
