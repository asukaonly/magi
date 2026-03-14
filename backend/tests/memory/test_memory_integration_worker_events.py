from __future__ import annotations

import unittest

from magi.events.events import BusinessEventTypes, Event, EventLevel, EventTypes
from magi.memory.integration import MemoryIntegrationConfig, MemoryIntegrationModule


class _FakeL1Raw:
    def __init__(self) -> None:
        self.stored_events = []

    async def store(self, event):
        self.stored_events.append(event)
        return "evt-1"


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.l1_raw = _FakeL1Raw()
        self.l2_relations = None
        self.l3_embeddings = None
        self.l4_summaries = None
        self.l5_capabilities = None


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
            self.assertIn(event_type, cfg.l1_event_whitelist)

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

        await integration._maybe_store_l1(event)

        self.assertEqual(len(integration.unified_memory.l1_raw.stored_events), 0)

    async def test_chat_response_action_preserves_trace_identity(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type=EventTypes.ACTION_EXECUTED,
            data={
                "action_type": "ChatResponseAction",
                "response": "Done.",
                "execution_time": 0.2,
                "user_id": "u1",
                "session_id": "s1",
                "turn_id": "turn_1",
                "orchestration_id": "orch_1",
            },
            source="test",
            level=EventLevel.INFO,
            correlation_id="corr-1",
        )

        transformed = integration._transform_to_business_event(event)

        self.assertEqual(transformed.type, BusinessEventTypes.AI_RESPONSE)
        self.assertEqual(transformed.data["turn_id"], "turn_1")
        self.assertEqual(transformed.data["orchestration_id"], "orch_1")

    async def test_tool_invoked_event_preserves_trace_identity(self):
        integration = MemoryIntegrationModule(
            unified_memory=_FakeUnifiedMemory(),
            message_bus=_FakeBus(),
            config=MemoryIntegrationConfig(),
        )

        event = Event(
            type=EventTypes.ACTION_EXECUTED,
            data={
                "action_type": "grep",
                "params": {"path": "/tmp/demo.py", "pattern": "qweather"},
                "success": True,
                "execution_time": 1.5,
                "user_id": "u1",
                "session_id": "s1",
                "turn_id": "turn_1",
                "orchestration_id": "orch_1",
                "tool_call_id": "call_1",
                "iteration": 2,
            },
            source="test",
            level=EventLevel.INFO,
            correlation_id="corr-2",
        )

        transformed = integration._transform_to_business_event(event)

        self.assertEqual(transformed.type, BusinessEventTypes.TOOL_INVOKED)
        self.assertEqual(transformed.data["user_id"], "u1")
        self.assertEqual(transformed.data["session_id"], "s1")
        self.assertEqual(transformed.data["turn_id"], "turn_1")
        self.assertEqual(transformed.data["orchestration_id"], "orch_1")
        self.assertEqual(transformed.data["tool_call_id"], "call_1")
        self.assertEqual(transformed.data["iteration"], 2)


if __name__ == "__main__":
    unittest.main()
