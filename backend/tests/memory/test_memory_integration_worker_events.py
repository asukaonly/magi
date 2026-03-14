from __future__ import annotations

import unittest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.integration import MemoryIntegrationConfig, MemoryIntegrationModule


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.ingested = []
        self.l0 = None
        self.l3 = None

    async def ingest_event(self, event):
        self.ingested.append(event)
        ingest_target = getattr(event, "ingest_target", None)
        return {
            "event_id": getattr(event, "event_id", "evt-1"),
            "ingest_target": ingest_target or "l1_only",
            "l1_written": ingest_target != "l0_only",
            "l2_relation_count": 0,
            "l2_assertion_count": 0,
            "l4_skill_id": None,
        }

    async def generate_summary(self, period_type: str = "hour"):
        _ = period_type
        return None


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


if __name__ == "__main__":
    unittest.main()
