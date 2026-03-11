"""Tests for L1-L5 unified memory flow and integration pipeline."""

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
from magi.timeline import TimelineContentBlock, TimelineEvent
from magi.timeline.service import TimelineService


class TestUnifiedMemoryStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.store = UnifiedMemoryStore(
            db_path=str(self.base / "events.db"),
            persist_dir=str(self.base / "memories"),
            enable_embeddings=True,
            enable_summaries=True,
            enable_capabilities=True,
            embedding_config={
                "backend": "sqlite_vec",
                "local_model": "hash",
                "local_dimension": 64,
            },
        )
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_l1_l5_pipeline(self):
        now = time.time()
        for idx in range(3):
            await self.store.add_event(
                {
                    "id": f"task-{idx}",
                    "type": EventTypes.TASK_COMPLETED,
                    "timestamp": now + idx,
                    "source": "test",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "task_id": "daily_report",
                        "success": True,
                        "duration": 0.3,
                        "action": {"tool": "summary_tool", "params": {"scope": "daily"}},
                    },
                    "metadata": {
                        "event_type": EventTypes.TASK_COMPLETED,
                        "message": "generate daily summary",
                        "parameters": {"scope": "daily"},
                    },
                }
            )

        l1_count = await self.store.l1_raw.count_events()
        self.assertEqual(l1_count, 3)

        l2_stats = self.store.l2_relations.get_statistics()
        self.assertEqual(l2_stats["total_events"], 3)

        semantic = await self.store.search("daily summary", search_type="semantic", limit=5)
        self.assertGreaterEqual(len(semantic), 1)

        summary = self.store.generate_summary("day", force=True)
        self.assertIsNotNone(summary)
        self.assertGreater(summary.event_count, 0)

        capabilities = self.store.l5_capabilities.get_all_capabilities()
        self.assertGreaterEqual(len(capabilities), 1)

        found = self.store.find_capability(
            {
                "event_type": EventTypes.TASK_COMPLETED,
                "message": "please generate daily summary",
                "parameters": {"scope": "daily"},
            },
            threshold=0.1,
        )
        self.assertIsNotNone(found)

    async def test_timeline_events_round_trip_through_l1(self):
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
            content_blocks=[TimelineContentBlock(kind="text", value="Today was full and calm.")],
            processing_status={"stored": True, "embedded": False},
            provenance={"sensor_id": "manual_journal"},
        )

        stored_id = await service.upsert_event(event)
        self.assertEqual(stored_id, "timeline-1")

        fetched = await self.store.l1_raw.get_timeline_event("timeline-1")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched["occurred_at"], event.occurred_at)
        self.assertEqual(fetched["captured_at"], event.captured_at)
        self.assertEqual(fetched["retention_mode"], "retain_raw")
        self.assertEqual(fetched["raw_payload_ref"], "/tmp/day-note.md")
        self.assertEqual(fetched["content_blocks"][0]["kind"], "text")
        self.assertEqual(fetched["processing_status"]["stored"], True)

        listed = await self.store.l1_raw.list_events(limit=10, event_type="TIMELINE_EVENT")
        self.assertEqual(listed[0]["id"], "timeline-1")
        self.assertEqual(listed[0]["metadata"]["timeline"]["title"], "Evening note")


class TestMemoryIntegrationModule(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)

        self.memory = UnifiedMemoryStore(
            db_path=str(base / "events.db"),
            persist_dir=str(base / "memories"),
            enable_embeddings=True,
            enable_summaries=True,
            enable_capabilities=True,
            embedding_config={"backend": "sqlite_vec", "local_model": "hash", "local_dimension": 32},
        )
        await self.memory.initialize()

        self.bus = MemoryMessageBackend()
        await self.bus.start()

        self.integration = MemoryIntegrationModule(
            unified_memory=self.memory,
            message_bus=self.bus,
            config=MemoryIntegrationConfig(summary_interval_minutes=1),
        )
        await self.integration.start()

    async def asyncTearDown(self) -> None:
        await self.integration.stop()
        await self.bus.stop()
        self.temp_dir.cleanup()

    async def test_event_pipeline_from_bus(self):
        correlation_id = "corr-1"
        await self.bus.publish(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "message": "hello"},
                source="test",
                level=EventLevel.INFO,
                correlation_id=correlation_id,
            )
        )

        await self.bus.publish(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "task_id": "chat_reply",
                    "success": True,
                    "duration": 0.2,
                    "action": {"tool": "reply_tool"},
                    "user_id": "u1",
                },
                source="test",
                level=EventLevel.INFO,
                correlation_id=correlation_id,
                metadata={"event_type": EventTypes.TASK_COMPLETED, "message": "reply to user"},
            )
        )

        await asyncio.sleep(0.5)

        stats = self.integration.get_statistics()
        self.assertGreaterEqual(stats["events_processed"], 2)
        self.assertGreaterEqual(stats["l1_stored"], 1)

        l1_count = await self.memory.l1_raw.count_events()
        self.assertGreaterEqual(l1_count, 1)

        l2_stats = self.memory.l2_relations.get_statistics()
        self.assertGreaterEqual(l2_stats["total_events"], 2)

        await self.integration.generate_pending_summaries()
        summary = self.memory.get_summary("hour")
        self.assertTrue(summary is None or summary.event_count >= 1)


if __name__ == "__main__":
    unittest.main()
