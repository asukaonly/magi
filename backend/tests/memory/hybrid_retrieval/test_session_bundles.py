from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.memory.hybrid_retrieval.evidence.session_bundles import EvidenceBundleMixin


class _SessionEventStore:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    async def query_events(self, *, session_id: str, limit: int = 100, **kwargs: Any) -> list[dict[str, Any]]:
        user_id = str(kwargs.get("user_id") or "").strip()
        return [
            event
            for event in self.events
            if event.get("session_id") == session_id
            and (not user_id or event.get("user_id") == user_id)
        ][:limit]

    async def query_session_event_window(
        self,
        *,
        session_id: str,
        center_session_seq: int,
        window: int,
        user_id: str | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        _ = kwargs
        start = center_session_seq - window
        end = center_session_seq + window
        normalized_user_id = str(user_id or "").strip()
        events = [
            event
            for event in self.events
            if event.get("session_id") == session_id
            and start <= int(event.get("session_seq", -1)) <= end
            and (not normalized_user_id or event.get("user_id") == normalized_user_id)
        ]
        events.sort(key=lambda event: int(event.get("session_seq", 0)))
        return events[:limit] if limit is not None else events


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
async def test_evidence_bundle_scopes_session_sequence_neighbors_by_user_id() -> None:
    same_session_events = [
        {
            "event_id": f"user-a-{index}",
            "session_id": "shared-session",
            "turn_id": f"a-turn-{index}",
            "session_seq": index,
            "user_id": "user-a",
            "timestamp": float(index),
            "content": f"user A message {index}",
            "retrieval_score": 0.1,
        }
        for index in range(20)
    ] + [
        {
            "event_id": f"user-b-{index}",
            "session_id": "shared-session",
            "turn_id": f"b-turn-{index}",
            "session_seq": index,
            "user_id": "user-b",
            "timestamp": float(index),
            "content": f"user B message {index}",
            "retrieval_score": 0.1,
        }
        for index in range(20)
    ]
    hit = dict(same_session_events[10])
    hit["retrieval_score"] = 0.9

    bundles = await _EvidenceBundleHost(same_session_events)._build_l1_evidence_bundles(
        [hit],
        query="message",
        user_id="user-a",
    )

    assert len(bundles) == 1
    assert [event["event_id"] for event in bundles[0]["events"]] == [
        f"user-a-{index}" for index in range(5, 16)
    ]
    assert all(event["user_id"] == "user-a" for event in bundles[0]["events"])


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
