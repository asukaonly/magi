from __future__ import annotations

import unittest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.integration import MemoryIntegrationConfig, MemoryIntegrationModule


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.ingested = []
        self.l0 = None
        self.l3 = None

    def _normalize_event(self, event):
        return normalize_runtime_event(event)

    async def ingest_event(self, event):
        self.ingested.append(event)
        ingest_target = getattr(event, "ingest_target", None)
        return {
            "event_id": getattr(event, "event_id", "evt-1"),
            "ingest_target": ingest_target or "l1_only",
            "l1_written": ingest_target != "runtime_only",
            "l2_relation_count": 0,
            "l2_assertion_count": 0,
            "l4_skill_id": None,
        }

    async def generate_summary(self, period_type: str = "hour"):
        _ = period_type
        return None

    def get_l2_pipeline_stats(self):
        return {}


class _FakeBus:
    async def subscribe(self, *args, **kwargs):  # pragma: no cover - not used in this unit test
        return "sub-1"

    async def unsubscribe(self, *args, **kwargs):  # pragma: no cover - not used in this unit test
        return True


class TestMemoryIntegrationWorkerEvents(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_include_worker_events(self):
        cfg = MemoryIntegrationConfig()
        for event_type in (
            "WORKER_AGENT_PROGRESS",
            "WORKER_AGENT_COMPLETED",
            "WORKER_AGENT_FAILED",
        ):
            self.assertIn(event_type, cfg.subscribed_events)
        for event_type in (
            "CHAT_TOOL_LOOP_STEP",
            "TOOL_INTERACTION",
            "TOOL_INVOKED",
            "TURN_TRACE_STARTED",
            "TURN_TRACE_COMPLETED",
            "TURN_TRACE_FAILED",
            "TRACE_NODE_STARTED",
            "TRACE_NODE_COMPLETED",
            "TRACE_NODE_FAILED",
        ):
            self.assertNotIn(event_type, cfg.subscribed_events)
        self.assertNotIn(EventTypes.USER_MESSAGE, cfg.subscribed_events)
        self.assertNotIn(EventTypes.AI_RESPONSE, cfg.subscribed_events)

    async def test_bus_handler_rejects_event_without_publication_epoch(self):
        memory = _FakeUnifiedMemory()
        integration = MemoryIntegrationModule(
            unified_memory=memory,
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        await integration._handle_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "task_id": "task-1",
                    "success": True,
                },
                source="runtime",
            )
        )

        self.assertEqual(memory.ingested, [])
        self.assertEqual(integration.get_statistics()["events_failed"], 1)

    async def test_worker_progress_event_is_not_stored_in_l1(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type="WORKER_AGENT_PROGRESS",
            data={"user_id": "u1", "session_id": "s1", "worker_id": "worker_abc"},
            source="test",
            level=EventLevel.INFO,
            correlation_id="worker_abc",
        )

        stored = await integration._maybe_store_l1(event)

        self.assertFalse(stored)

    async def test_worker_completion_events_are_not_stored_in_l1(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        for event_type in ("WORKER_AGENT_COMPLETED", "WORKER_AGENT_FAILED"):
            event = Event(
                type=event_type,
                data={"user_id": "u1", "session_id": "s1", "worker_id": "worker_abc"},
                source="test",
                level=EventLevel.INFO,
                correlation_id=f"{event_type.lower()}-worker_abc",
            )

            stored = await integration._maybe_store_l1(event)

            self.assertFalse(stored)

    async def test_task_completed_event_can_be_routed_to_l1(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type=EventTypes.TASK_COMPLETED,
            data={"user_id": "u1", "session_id": "s1", "task_id": "task-1", "success": True},
            source="runtime",
            level=EventLevel.INFO,
            correlation_id="task-1",
        )

        stored = await integration._maybe_store_l1(event)

        self.assertTrue(stored)

    async def test_chat_tool_loop_step_event_is_not_stored_in_l1(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type="CHAT_TOOL_LOOP_STEP",
            data={"user_id": "u1", "session_id": "s1", "tool_name": "web_search"},
            source="runtime",
            level=EventLevel.INFO,
            correlation_id="turn-1",
        )

        stored = await integration._maybe_store_l1(event)

        self.assertFalse(stored)

    async def test_tool_invoked_event_is_not_stored_in_l1(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type="TOOL_INVOKED",
            data={"user_id": "u1", "session_id": "s1", "tool_name": "web_search"},
            source="runtime",
            level=EventLevel.INFO,
            correlation_id="turn-2",
        )

        stored = await integration._maybe_store_l1(event)

        self.assertFalse(stored)

    async def test_trace_node_event_is_not_stored_in_l1(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type="TRACE_NODE_COMPLETED",
            data={
                "trace_id": "trace:turn-3",
                "turn_id": "turn-3",
                "span_id": "turn-3:llm_call:direct",
                "parent_span_id": "turn-3:turn",
                "node_type": "llm_call",
                "name": "Main LLM call",
                "status": "completed",
                "duration_ms": 512,
                "tags": {
                    "user_id": "u1",
                    "session_id": "s1",
                },
            },
            source="runtime_event_emitter",
            level=EventLevel.INFO,
            correlation_id="turn-3:llm_call:direct",
        )

        stored = await integration._maybe_store_l1(event)

        self.assertFalse(stored)


if __name__ == "__main__":
    unittest.main()
