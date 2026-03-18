"""End-to-end tests for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from magi.events.events import Event, EventLevel, EventTypes
from magi.events.memory_backend import MemoryMessageBackend
from magi.memory import UnifiedMemoryStore
from magi.memory.integration import MemoryIntegrationConfig, MemoryIntegrationModule
from magi.memory.l3.models import L3Candidate, TaskOutcomePacket
from magi.timeline import TimelineContentBlock, TimelineEvent
from magi.timeline.service import TimelineService


class TestUnifiedMemoryStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "l1_events.db"),
            memory_db_path=str(self.base / "memory.db"),
            persist_dir=str(self.base / "memories"),
        )
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_l0_l4_pipeline(self):
        now = time.time()
        await self.store.add_event(
            {
                "id": "evt-1",
                "type": EventTypes.USER_MESSAGE,
                "timestamp": now,
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "message": "I have been really stressed about work lately.",
                },
                "metadata": {"user_id": "u1"},
            }
        )
        await self.store.add_event(
            {
                "id": "evt-2",
                "type": EventTypes.ACTION_EXECUTED,
                "timestamp": now + 5,
                "source": "worker",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "action_type": "browser.open",
                    "params": {"url": "https://example.com"},
                    "success": True,
                    "execution_time": 0.5,
                },
            }
        )
        await self.store.add_event(
            {
                "id": "evt-3",
                "type": EventTypes.ACTION_EXECUTED,
                "timestamp": now + 10,
                "source": "worker",
                "level": EventLevel.ERROR.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "action_type": "browser.open",
                    "params": {"url": "https://example.com"},
                    "success": False,
                    "execution_time": 0.5,
                    "error": "timeout",
                },
            }
        )

        workbench = await self.store.l0.get_workbench("s1")
        l1_count = await self.store.l1.count_events()
        runtime_count = await self.store.l1.count_runtime_observations()
        assertions = await self.store.l2.list_tom_assertions(entity_id="user:self")
        summary = await self.store.generate_summary(period_type="day", period_start=now - 10, period_end=now + 60)
        procedures = await self.store.l4.query_strategies(query="browser", limit=5)

        self.assertEqual(workbench["session"]["user_id"], "u1")
        self.assertEqual(l1_count, 1)
        self.assertEqual(runtime_count, 2)
        self.assertEqual(assertions[0]["trait_name"], "stress_level")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["summary_type"], "temporal")
        self.assertGreaterEqual(len(procedures), 1)

    async def test_timeline_events_round_trip_through_l1_and_l2(self):
        service = TimelineService(self.store)
        event = TimelineEvent(
            event_id="timeline-1",
            source_type="manual_journal",
            source_item_id="manual-1",
            occurred_at=time.time() - 5,
            captured_at=time.time(),
            title="Evening note",
            summary="Wrote about the day",
            retention_mode="retain_raw",
            raw_payload_ref="/tmp/day-note.md",
            content_blocks=[TimelineContentBlock(kind="text", value="Today I said I like Asuka.")],
            processing_status={"stored": True, "embedded": False},
            provenance={"sensor_id": "manual_journal"},
        )

        stored_id = await service.upsert_event(
            event,
            relation_candidates=[
                {
                    "subject_id": "user:self",
                    "subject_type": "user",
                    "predicate": "LIKES",
                    "object_id": "character:asuka",
                    "object_type": "person",
                    "confidence": 0.85,
                }
            ],
            allowed_edge_whitelist=["LIKES"],
        )

        fetched = await self.store.l1.get_timeline_event("timeline-1")
        listed = await self.store.l1.list_timeline_events(limit=10, source_type="manual_journal")
        detail = await service.get_event_detail("timeline-1")

        self.assertEqual(stored_id, "timeline-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["retention_mode"], "retain_raw")
        self.assertEqual(listed[0]["title"], "Evening note")
        self.assertEqual(detail["graph_evidence"][0]["predicate"], "LIKES")

    async def test_persist_l3_candidate_writes_validated_task_reflection(self):
        now = time.time()
        await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "message": "I care more about growth than salary."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=now,
            )
        )
        await self.store.add_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"user_id": "u1", "session_id": "s1", "response": "You should finish your portfolio homepage first."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=now + 1,
            )
        )

        event_ids = [row["event_id"] for row in await self.store.l1.query_events(limit=10)]
        summary = await self.store.persist_l3_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="task_reflection",
                content="The user clarified that growth matters more than salary and should finish the portfolio homepage before applying.",
                source_event_ids=event_ids,
            ),
            task_outcome=TaskOutcomePacket(
                task_id="task-1",
                user_id="u1",
                task_title="Plan job switch",
                task_status="completed",
                user_goal="Decide whether to start applying this month",
                result_summary="Clarified priorities and next steps for a job switch.",
                evidence_event_ids=event_ids,
                decisions=[{"content": "Growth matters more than salary."}],
                next_steps=["Finish the portfolio homepage."],
            ),
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary["summary_category"], "task_reflection")
        event_links = await self.store.l3.list_summary_event_links(summary["summary_id"])
        self.assertEqual(len(event_links), 2)

    async def test_persist_task_outcome_reflection_builds_and_writes_summary(self):
        now = time.time()
        await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "message": "I care more about growth than salary."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=now,
            )
        )
        await self.store.add_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"user_id": "u1", "session_id": "s1", "response": "You should finish your portfolio homepage first."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=now + 1,
            )
        )

        event_ids = [row["event_id"] for row in await self.store.l1.query_events(limit=10)]
        summary = await self.store.persist_task_outcome_reflection(
            TaskOutcomePacket(
                task_id="task-2",
                user_id="u1",
                task_kind="user_goal_task",
                task_title="Plan job switch",
                task_status="completed",
                user_goal="Decide whether to start applying this month",
                result_summary="Clarified priorities and next steps for a job switch.",
                evidence_event_ids=event_ids,
                decisions=[{"content": "Growth matters more than salary."}],
                next_steps=["Finish the portfolio homepage."],
            )
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary["summary_category"], "task_reflection")
        task_links = await self.store.l3.list_summary_task_links(summary["summary_id"])
        self.assertEqual(task_links[0]["task_id"], "task-2")


class TestMemoryIntegrationModule(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)

        self.memory = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
        )
        await self.memory.initialize()

        self.bus = MemoryMessageBackend()
        await self.bus.start()

        self.integration = MemoryIntegrationModule(
            unified_memory=self.memory,
            message_bus=self.bus,
            config=MemoryIntegrationConfig(),
        )
        await self.integration.start()

    async def asyncTearDown(self) -> None:
        await self.integration.stop()
        await self.bus.stop()
        self.temp_dir.cleanup()

    async def test_event_pipeline_from_bus(self):
        await self.bus.publish(
            Event(
                type="WORKER_AGENT_PROGRESS",
                data={"user_id": "u1", "session_id": "s1", "worker_id": "worker-1"},
                source="worker",
                level=EventLevel.INFO,
                correlation_id="corr-1",
            )
        )
        await self.bus.publish(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "message": "I feel stressed at work."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-1",
            )
        )
        await self.bus.publish(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={"user_id": "u1", "session_id": "s1", "task_id": "reply", "success": True},
                source="runtime",
                level=EventLevel.INFO,
                correlation_id="corr-1",
            )
        )

        await asyncio.sleep(0.2)

        stats = self.integration.get_statistics()
        workbench = await self.memory.l0.get_workbench("s1")
        l1_count = await self.memory.l1.count_events()
        runtime_count = await self.memory.l1.count_runtime_observations()

        self.assertGreaterEqual(stats["events_processed"], 3)
        self.assertEqual(l1_count, 1)
        self.assertEqual(runtime_count, 1)
        self.assertEqual(workbench["session"]["user_id"], "u1")
        self.assertGreaterEqual(stats["l2_assertions_written"], 1)


if __name__ == "__main__":
    unittest.main()
