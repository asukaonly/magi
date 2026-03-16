from __future__ import annotations

import pytest

from magi.config import AppConfig
from magi.timeline import TimelineContentBlock, TimelineEvent
from magi.timeline.handler import build_timeline_handler


class _FakeL1Store:
    def __init__(self) -> None:
        self.timeline_events = []

    async def store_timeline_event(self, event) -> str:
        self.timeline_events.append(event)
        return event.event_id


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l1 = _FakeL1Store()
        self.edges: list[dict] = []

    async def upsert_user_graph_edge(self, **kwargs) -> None:
        self.edges.append(kwargs)


class _FakeChatSensor:
    async def build_timeline_event(self, payload):  # type: ignore[no-untyped-def]
        turn_id = str(payload["turn_id"])
        return TimelineEvent(
            event_id=f"chat:{turn_id}",
            source_type="chat",
            source_item_id=turn_id,
            occurred_at=float(payload["timestamp"]),
            captured_at=float(payload["timestamp"]),
            title="Chat Turn",
            summary=str(payload["message"]),
            retention_mode="analyze_only",
            content_blocks=[
                TimelineContentBlock(kind="text", value=f"User: {payload['message']}"),
                TimelineContentBlock(kind="text", value=f"Assistant: {payload['assistant_message']}"),
            ],
            processing_status={"stored": True},
            provenance={"session_id": str(payload.get("session_id") or "")},
            tags=["chat"],
        )

    async def extract_candidates(self, payload):  # type: ignore[no-untyped-def]
        return {
            "entities": [],
            "tags": ["chat"],
            "relation_candidates": list(payload.get("relation_candidates", [])),
        }


class _FakeSensorRegistry:
    def resolve_domain_sensor(self, domain: str, source_type: str):
        if domain != "timeline" or source_type != "chat":
            return None
        spec = type("Spec", (), {"metadata": {"default_settings": {"enabled": True, "edge_whitelist": ["LIKES"]}}})()
        return ("core-timeline", "timeline.chat", _FakeChatSensor(), spec)


class _FakePluginManager:
    def get_package(self, plugin_id: str):
        if plugin_id != "core-timeline":
            return None
        return type("Package", (), {"current_settings": {"sensors": {"chat": {"enabled": True}}}})()


@pytest.mark.asyncio
async def test_runtime_timeline_handler_persists_chat_turn_and_user_graph_edges() -> None:
    memory = _FakeUnifiedMemory()
    handler = build_timeline_handler(
        AppConfig(),
        memory,
        sensor_registry=_FakeSensorRegistry(),
        plugin_manager=_FakePluginManager(),
    )

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
    assert len(memory.l1.timeline_events) == 1
    stored_event = memory.l1.timeline_events[0]
    assert stored_event.provenance["session_id"] == "session-1"
    assert [block.value for block in stored_event.content_blocks] == [
        "User: I still like Asuka best.",
        "Assistant: You mention Asuka often.",
    ]
    assert len(memory.edges) == 1
    assert memory.edges[0]["predicate"] == "LIKES"
