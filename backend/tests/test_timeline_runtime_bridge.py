from __future__ import annotations

import pytest

from magi.config import AppConfig
from magi.runtime.bootstrap import _build_timeline_handler


class _FakeL1RawStore:
    def __init__(self) -> None:
        self.timeline_events = []

    async def store_timeline_event(self, event) -> str:
        self.timeline_events.append(event)
        return event.event_id


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l1_raw = _FakeL1RawStore()
        self.edges: list[dict] = []

    def upsert_user_graph_edge(self, **kwargs) -> None:
        self.edges.append(kwargs)


@pytest.mark.asyncio
async def test_runtime_timeline_handler_persists_chat_turn_and_user_graph_edges() -> None:
    memory = _FakeUnifiedMemory()
    handler = _build_timeline_handler(AppConfig(), memory)

    result = await handler(
        {
            "target_task_agent_id": "timeline-main",
            "source_type": "chat",
            "source_item_id": "turn-1",
            "turn_id": "turn-1",
            "user_id": "web_user",
            "session_id": "session-1",
            "message": "I still like Asuka best.",
            "assistant_message": "You mention Asuka often.",
            "timestamp": 1710000000.0,
            "relation_candidates": [
                {
                    "subject_id": "user:self",
                    "subject_type": "user",
                    "predicate": "LIKES",
                    "object_id": "person:asuka",
                    "object_type": "person",
                    "confidence": 0.91,
                }
            ],
        }
    )

    assert result == {"handled": True, "event_id": "chat:turn-1", "source_type": "chat"}
    assert len(memory.l1_raw.timeline_events) == 1
    stored_event = memory.l1_raw.timeline_events[0]
    assert stored_event.provenance["session_id"] == "session-1"
    assert [block.value for block in stored_event.content_blocks] == [
        "User: I still like Asuka best.",
        "Assistant: You mention Asuka often.",
    ]
    assert len(memory.edges) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
