"""End-to-end tests for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiosqlite

from magi.events.events import Event, EventLevel, EventTypes
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.memory import MemoryStoreTuning, UnifiedMemoryStore
from magi.memory.event_contracts import IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth
from magi.memory.integration import MemoryIntegrationConfig, MemoryIntegrationModule
from magi.memory.l2.models import ReconciledTraitOutcome
from magi.memory.l3.models import L3Candidate, StateChangePacket, TaskOutcomePacket
from magi.timeline.contracts import TimelineContentBlock, TimelineEvent
from magi.timeline.service import TimelineService


# Phase 1 plus optional Phase 2 wording for a current mood assertion.
_STRESS_PHASE1 = json.dumps({
    "entities": [],
    "fact_claims": [
        {
            "subject_ref": "user:self",
            "predicate": "FEELS",
            "object_ref": "stressed",
            "object_type": "concept",
            "fact_kind": "explicit_fact",
            "temporal_cue": "recent",
            "polarity": "negative",
            "specificity": "concrete",
            "evidence_text": "I have been really stressed about work lately.",
            "confidence": 0.90,
            "supporting_event_ids": [],
        }
    ],
    "resolved_refs": [],
    "diagnostics": {"entity_status": "none"},
})

_STRESS_PHASE2 = json.dumps({"summaries": []})

_PLACE_PHASE1 = json.dumps({
    "entities": [
        {
            "surface": "魔都",
            "normalized_name": "上海",
            "entity_type": "place",
            "specificity": "concrete",
            "resolved_id": "place:shanghai",
            "is_new": False,
            "alias_signals": ["魔都"],
            "confidence": 0.96,
        }
    ],
    "fact_claims": [
        {
            "subject_ref": "user:self",
            "predicate": "LIKES",
            "object_ref": "魔都",
            "object_type": "place",
            "fact_kind": "stable_preference",
            "temporal_cue": "unspecified",
            "polarity": "positive",
            "specificity": "concrete",
            "evidence_text": "我好喜欢魔都",
            "confidence": 0.96,
            "supporting_event_ids": ["evt-place-1"],
        }
    ],
    "resolved_refs": [],
    "diagnostics": {"entity_status": "found"},
})

_PLACE_PHASE2 = json.dumps({"summaries": []})


class _FakeAdapter:
    """Adapter that returns appropriate Phase 1 / Phase 2 responses based on system prompt."""

    def __init__(self, phase1: str, phase2: str) -> None:
        self._phase1 = phase1
        self._phase2 = phase2
        self.provider_name = "openai"
        self.model_name = "gpt-test"
        self._client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=self._create_completion),
            )
        )

    async def _create_completion(self, **kwargs):  # type: ignore[no-untyped-def]
        system_prompt = ""
        messages = kwargs.get("messages") or []
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            system_prompt = str(messages[0].get("content") or "")
        text = (
            self._phase2
            if "optional natural-language summaries" in system_prompt
            else self._phase1
        )
        message = SimpleNamespace(content=text, tool_calls=[], role="assistant")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=None,
        )


class _FakeScenarioPool:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self._adapter = adapter

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return self._adapter


async def _wait_for_async_condition(predicate, *, timeout: float = 1.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(interval)
    return await predicate()


class TestUnifiedMemoryStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "l1_events.db"),
            memory_db_path=str(self.base / "memory.db"),
            persist_dir=str(self.base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(_FakeAdapter(_STRESS_PHASE1, _STRESS_PHASE2)),
        )
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.store.shutdown()
        self.temp_dir.cleanup()

    async def test_memory_pipeline_does_not_implicitly_write_l0(self):
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
                    "content": "I have been really stressed about work lately.",
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
        assertions = await _wait_for_async_condition(
            lambda: self.store.l2.list_tom_assertions(entity_id="user:u1")
        )
        summary = await self.store.generate_summary(period_type="day", period_start=now - 10, period_end=now + 60)
        procedures = await _wait_for_async_condition(
            lambda: self.store.l4.query_strategies(query="browser", limit=5)
        )

        self.assertIsNone(workbench["session"])
        self.assertEqual(workbench["attention_items"], [])
        self.assertEqual(l1_count, 1)
        self.assertEqual(assertions[0]["trait_name"], "mood")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["summary_type"], "temporal")
        self.assertGreaterEqual(len(procedures), 1)

    async def test_l1_ingest_enqueues_durable_l2_projection_job(self):
        result = await self.store.ingest_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I have been really stressed about work lately."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-proj-1",
                metadata={"user_id": "u1"},
                timestamp=time.time(),
            )
        )

        async with aiosqlite.connect(str(self.base / "memory.db")) as db:
            cursor = await db.execute(
                """
                SELECT status, source, event_type
                FROM l2_projection_jobs
                WHERE event_id = ?
                """,
                (str(result["event_id"]),),
            )
            row = await cursor.fetchone()

        self.assertEqual(row, ("pending", "chat", EventTypes.USER_MESSAGE))

    async def test_duplicate_l1_ingest_does_not_duplicate_l2_projection_job(self):
        """Test that re-ingesting the same event (same envelope_id + same idempotency_key)
        does not create duplicate L2 projection jobs. Per spec §12.1, legitimate dedupes
        are when the same envelope id is replayed."""
        now = time.time()
        event = MemoryEvent(
            event_id="evt-dup-1",
            correlation_id="corr-dup",
            timestamp=now,
            created_at=now,
            event_type=EventTypes.USER_MESSAGE,
            source="chat",
            source_item_id="chat:dup",
            memory_domain=MemoryDomain.USER_AUTHORED,
            ingest_target=IngestTarget.L1_ONLY,
            cognition_eligible=True,
            tom_depth=TomDepth.DEFENSIVE_PSYCHOLOGY,
            retention_class=RetentionClass.COMPRESSIBLE,
            session_id="s1",
            turn_id="t1",
            user_id="u1",
            task_id=None,
            content="I have been really stressed about work lately.",
            author_type="user",
            content_type="text",
            importance_score=0.8,
            level=EventLevel.INFO.value,
            metadata_json={},
            idempotency_key="chat:dup",
        )

        # Ingest the same event twice (same envelope_id + same idempotency_key)
        first_result = await self.store.ingest_event(event)
        second_result = await self.store.ingest_event(event)

        async with aiosqlite.connect(str(self.base / "memory.db")) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM l2_projection_jobs")
            count_row = await cursor.fetchone()

        # Same envelope id on both results (dedupe succeeded)
        self.assertEqual(first_result["event_id"], second_result["event_id"])
        self.assertEqual(first_result["event_id"], "evt-dup-1")
        # Only one L2 projection job created
        self.assertEqual(count_row, (1,))

    async def test_l2_pipeline_claims_and_completes_durable_projection_jobs(self):
        result = await self.store.ingest_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I have been really stressed about work lately."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-proj-2",
                metadata={"user_id": "u1"},
                timestamp=time.time(),
            )
        )

        async def _projection_completed() -> bool:
            async with aiosqlite.connect(str(self.base / "memory.db")) as db:
                cursor = await db.execute(
                    """
                    SELECT status
                    FROM l2_projection_jobs
                    WHERE event_id = ?
                    """,
                    (str(result["event_id"]),),
                )
                row = await cursor.fetchone()
            return row == ("completed",)

        await _wait_for_async_condition(
            _projection_completed,
            timeout=2.0,
            interval=0.05,
        )

    async def test_action_executed_is_excluded_from_l1_but_still_updates_l4(self):
        now = time.time()

        await self.store.add_event(
            {
                "id": "evt-action-only-1",
                "type": EventTypes.ACTION_EXECUTED,
                "timestamp": now,
                "source": "runtime_event_emitter",
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

        l1_events = await self.store.l1.query_events(limit=10)
        procedures = await _wait_for_async_condition(
            lambda: self.store.l4.query_strategies(query="browser", limit=5)
        )

        self.assertEqual(l1_events, [])
        self.assertGreaterEqual(len(procedures), 1)

    async def test_l2_ingest_does_not_implicitly_write_l0_attention(self):
        local_store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "entity_l1_events.db"),
            memory_db_path=str(self.base / "entity_memory.db"),
            persist_dir=str(self.base / "entity_memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(_FakeAdapter(_PLACE_PHASE1, _PLACE_PHASE2)),
        )
        await local_store.initialize()

        try:
            assert local_store.l2_entity_catalog is not None
            await local_store.l2_entity_catalog.upsert_entity(
                entity_id="place:shanghai",
                canonical_name="Shanghai",
                entity_type="place",
            )
            await local_store.l2_entity_catalog.add_alias(
                entity_id="place:shanghai",
                alias_text="魔都",
                confidence=0.98,
            )

            await local_store.add_event(
                {
                    "id": "evt-place-1",
                    "type": EventTypes.USER_MESSAGE,
                    "timestamp": time.time(),
                    "source": "chat",
                    "level": EventLevel.INFO.value,
                    "data": {
                        "user_id": "u1",
                        "session_id": "s1",
                        "content": "我好喜欢魔都",
                    },
                }
            )

            mentions = await _wait_for_async_condition(
                lambda: local_store.l2_entity_catalog.list_mentions(limit=10)
            )
            workbench = await local_store.l0.get_workbench("s1")

            self.assertEqual(len(mentions), 1)
            self.assertEqual(mentions[0]["resolved_entity_id"], "place:shanghai")
            self.assertEqual(workbench["attention_items"], [])
        finally:
            await local_store.shutdown()

    async def test_generate_summary_respects_l3_llm_toggle(self):
        local_store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "toggle_l1_events.db"),
            memory_db_path=str(self.base / "toggle_memory.db"),
            persist_dir=str(self.base / "toggle_memories"),
            tuning=MemoryStoreTuning(enable_l3_llm_summary=False),
        )
        await local_store.initialize()

        now = time.time()
        await local_store.add_event(
            {
                "id": "evt-toggle-1",
                "type": EventTypes.USER_MESSAGE,
                "timestamp": now,
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I want to switch jobs this year.",
                },
                "metadata": {"user_id": "u1"},
            }
        )

        async def _unexpected_model(_pack, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("LLM path should be disabled")

        self.assertIsNotNone(local_store.l3)
        local_store.l3._temporal_llm_service._call_temporal_model = _unexpected_model

        with patch(
            "magi.memory.l3.temporal_fallback.target_language_code",
            return_value="en",
        ):
            summary = await local_store.generate_summary(
                period_type="day",
                period_start=now - 10,
                period_end=now + 60,
            )

        self.assertIsNotNone(summary)
        self.assertEqual(summary["generated_by_model"], "rule-summary")
        self.assertIn("switch jobs", summary["content"].lower())
        await local_store.shutdown()

    async def test_unified_memory_store_passes_temporal_llm_timeout(self):
        local_store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "timeout_l1_events.db"),
            memory_db_path=str(self.base / "timeout_memory.db"),
            persist_dir=str(self.base / "timeout_memories"),
            tuning=MemoryStoreTuning(temporal_l3_llm_timeout_seconds=1.5),
        )
        await local_store.initialize()

        self.assertIsNotNone(local_store.l3)
        self.assertEqual(local_store.l3._temporal_llm_service._llm_timeout_seconds, 1.5)

        await local_store.shutdown()

    async def test_unified_memory_store_passes_temporal_llm_min_event_count(self):
        local_store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "threshold_l1_events.db"),
            memory_db_path=str(self.base / "threshold_memory.db"),
            persist_dir=str(self.base / "threshold_memories"),
            tuning=MemoryStoreTuning(temporal_l3_llm_min_event_count=3),
        )
        await local_store.initialize()

        self.assertIsNotNone(local_store.l3)
        self.assertEqual(local_store.l3._temporal_llm_service._min_event_count_for_llm, 3)

        await local_store.shutdown()

    async def test_generate_thematic_summary_returns_topic_summary(self):
        now = time.time()
        await self.store.add_event(
            {
                "id": "evt-topic-1",
                "type": EventTypes.USER_MESSAGE,
                "timestamp": now,
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I want to switch jobs this year.",
                },
                "metadata": {"user_id": "u1"},
            }
        )
        await self.store.add_event(
            {
                "id": "evt-topic-2",
                "type": EventTypes.AI_RESPONSE,
                "timestamp": now + 5,
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "The job market looks stronger for remote roles.",
                },
                "metadata": {"user_id": "u1"},
            }
        )

        summary = await self.store.generate_thematic_summary(topic="job", min_source_count=2)

        self.assertIsNotNone(summary)
        self.assertEqual(summary["summary_type"], "thematic")
        self.assertEqual(summary["summary_category"], "topic")
        self.assertEqual(summary["key_topics"], ["job"])

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

        await self.store.add_event(
            MemoryEvent(
                event_id="timeline-1",
                correlation_id="timeline-1",
                timestamp=event.occurred_at,
                created_at=event.captured_at,
                event_type="SENSOR_EVENT",
                source="manual_journal",
                source_item_id="manual-1",
                memory_domain=MemoryDomain.USER_AUTHORED,
                ingest_target=IngestTarget.L1_ONLY,
                cognition_eligible=True,
                tom_depth=TomDepth.DEFENSIVE_PSYCHOLOGY,
                retention_class=RetentionClass.PERMANENT,
                session_id=None,
                turn_id=None,
                user_id=None,
                task_id=None,
                content="Wrote about the day",
                author_type="user",
                content_type="text",
                importance_score=0.8,
                level=EventLevel.INFO.value,
                media_path="/tmp/day-note.md",
                metadata_json={
                    "activity_snapshot": event.to_dict(),
                    "raw_payload_ref": "/tmp/day-note.md",
                    "processing_status": {"stored": True, "embedded": False},
                },
            )
        )

        stored_id = await service.upsert_event(
            event,
            relation_candidates=[
                {
                    "subject_id": "user:u1",
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
        context = await service.get_context_bundle("timeline-1")

        self.assertEqual(stored_id, "timeline-1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["summary"], "Wrote about the day")
        self.assertEqual(listed[0]["title"], "Evening note")
        self.assertEqual(context["anchor"]["anchor_type"], "event")
        self.assertTrue(context["l2_state_evidence"])
        self.assertIn("timeline-1", context["l2_state_evidence"][0].get("evidence_events", []))

    async def test_persist_l3_candidate_writes_validated_task_reflection(self):
        now = time.time()
        await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I care more about growth than salary."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=now,
            )
        )
        await self.store.add_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"user_id": "u1", "session_id": "s1", "content": "You should finish your portfolio homepage first."},
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
                data={"user_id": "u1", "session_id": "s1", "content": "I care more about growth than salary."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=now,
            )
        )
        await self.store.add_event(
            Event(
                type=EventTypes.AI_RESPONSE,
                data={"user_id": "u1", "session_id": "s1", "content": "You should finish your portfolio homepage first."},
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

    async def test_persist_state_change_insight_builds_and_writes_summary(self):
        now = time.time()
        first_event_id = await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I have been stressed about work lately."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-state-1",
                timestamp=now,
            )
        )
        second_event_id = await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I still feel anxious and under pressure."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-state-2",
                timestamp=now + 1,
            )
        )

        summary = await self.store.persist_state_change_insight(
            StateChangePacket(
                entity_id="user:u1",
                entity_type="user",
                outcomes=[
                    # The unified insight renderer never leaks raw trait
                    # names; outcomes need a natural_summary (the L2 LLM
                    # writes one in production) or a known trait_family,
                    # otherwise the insight is intentionally skipped.
                    ReconciledTraitOutcome(
                        entity_id="user:u1",
                        entity_type="user",
                        trait_name="stress_level",
                        winning_value="high",
                        natural_summary="最近工作压力一直很大",
                        status="stable",
                        confidence=0.92,
                        evidence_event_ids=[first_event_id, second_event_id],
                        time_span_hours=48.0,
                        stability_kind="stable_pattern",
                        recommended_snapshot_field="core_traits",
                    ),
                    ReconciledTraitOutcome(
                        entity_id="user:u1",
                        entity_type="user",
                        trait_name="mood",
                        winning_value="anxious",
                        natural_summary="情绪持续偏焦虑",
                        status="corroborated",
                        confidence=0.81,
                        evidence_event_ids=[second_event_id],
                        time_span_hours=12.0,
                        stability_kind="emerging_pattern",
                        recommended_snapshot_field="core_traits",
                    ),
                ],
            )
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary["summary_type"], "insight")
        self.assertEqual(summary["summary_category"], "state_change")
        event_links = await self.store.l3.list_summary_event_links(summary["summary_id"])
        self.assertEqual(len(event_links), 2)

class TestUnifiedMemoryMaintenance(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "l1_events.db"),
            memory_db_path=str(self.base / "memory.db"),
            persist_dir=str(self.base / "memories"),
            enable_l0=False,
            enable_l4=False,
            tuning=MemoryStoreTuning(enable_l1_vectors=False, enable_l2_vectors=False, enable_l3_vectors=False),
        )
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.store.shutdown()
        self.temp_dir.cleanup()

    async def test_cleanup_old_data_soft_deletes_only_l3_covered_compressible_events(self):
        old_timestamp = time.time() - (40 * 86400)
        linked_compressible_event_id = await self.store.add_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "success": True,
                    "task_id": "task-docs-open",
                    "content": "Opened the reference docs successfully.",
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-gc-1",
                timestamp=old_timestamp,
            )
        )
        permanent_event_id = await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "This note should remain durable."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-gc-2",
                timestamp=old_timestamp + 1,
            )
        )
        uncovered_compressible_event_id = await self.store.add_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "success": True,
                    "task_id": "task-search-rules",
                    "content": "Searched for memory retention rules.",
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-gc-3",
                timestamp=old_timestamp + 2,
            )
        )

        await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="A compressed reflection covers the linked external action.",
                source_event_ids=[linked_compressible_event_id],
            )
        )

        removed = await self.store.cleanup_old_data(older_than_days=30)

        self.assertEqual(removed["deleted_events"], 1)
        self.assertEqual(await self.store.l1.count_events(), 2)
        self.assertIsNone((await self.store.l1.get_event(permanent_event_id))["deleted_at"])
        remaining_event_ids = {
            row["event_id"]
            for row in await self.store.l1.query_events(limit=10)
        }
        self.assertNotIn(linked_compressible_event_id, remaining_event_ids)
        self.assertIn(uncovered_compressible_event_id, remaining_event_ids)

    async def test_l1_cleanup_keeps_l2_referenced_events(self) -> None:
        old_timestamp = time.time() - (40 * 86400)
        linked_event_id = await self.store.add_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "success": True,
                    "task_id": "task-protected-episode",
                    "content": "A source event that still backs an active episode.",
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-l2-protected-1",
                timestamp=old_timestamp,
            )
        )
        await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="A summary covers this old event.",
                source_event_ids=[linked_event_id],
            ),
            summary_overrides={
                "period_start": old_timestamp,
                "period_end": old_timestamp,
                "created_at": old_timestamp,
                "updated_at": old_timestamp,
            },
        )
        await self.store.l2.create_episode(
            episode_id="ep-protect-l1-event",
            status="active",
            time_start=old_timestamp,
            time_end=old_timestamp + 60,
            label="Protected episode",
            source_event_count=1,
        )
        await self.store.l2.add_episode_events(
            episode_id="ep-protect-l1-event",
            event_ids=[linked_event_id],
        )

        removed = await self.store.cleanup_l1_data(older_than_days=30)

        self.assertEqual(removed["deleted_events"], 0)
        self.assertIsNone((await self.store.l1.get_event(linked_event_id))["deleted_at"])

    async def test_cleanup_old_data_can_archive_linked_events(self) -> None:
        old_timestamp = time.time() - (45 * 86400)
        linked_compressible_event_id = await self.store.add_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "task_id": "task-archive-history",
                    "success": True,
                    "content": "Archived a completed historical task.",
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-archive-1",
                timestamp=old_timestamp,
            )
        )

        await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="A compressed reflection covers the archived external action.",
                source_event_ids=[linked_compressible_event_id],
            ),
            summary_overrides={
                "period_start": old_timestamp,
                "period_end": old_timestamp,
                "created_at": old_timestamp,
                "updated_at": old_timestamp,
            },
        )

        removed = await self.store.cleanup_old_data(older_than_days=30, history_behavior="archive")

        self.assertEqual(removed["archived_events"], 1)
        self.assertEqual(removed["deleted_events"], 1)
        self.assertEqual(removed["archived_summaries"], 1)
        self.assertEqual(removed["deleted_summaries"], 1)
        self.assertEqual(await self.store.l3.count_summaries(), 0)

        archive_db_path = self.base / "memories" / "archive" / time.strftime("%Y-%m-%d", time.gmtime())
        archive_db_path = archive_db_path.with_suffix(".db")
        self.assertTrue(archive_db_path.exists())

        async with aiosqlite.connect(archive_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT event_id, payload_json FROM archived_l1_events WHERE event_id = ?",
                (linked_compressible_event_id,),
            ) as cursor:
                row = await cursor.fetchone()

        self.assertIsNotNone(row)
        payload = json.loads(str(row["payload_json"]))
        self.assertEqual(payload["event_id"], linked_compressible_event_id)
        self.assertEqual(payload["source"], "worker")

        async with aiosqlite.connect(archive_db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT summary_id, payload_json FROM archived_l3_summaries"
            ) as cursor:
                summary_row = await cursor.fetchone()

        self.assertIsNotNone(summary_row)
        summary_payload = json.loads(str(summary_row["payload_json"]))
        self.assertEqual(summary_payload["summary"]["summary_id"], str(summary_row["summary_id"]))
        self.assertEqual(summary_payload["summary"]["summary_category"], "state_change")

    async def test_l1_archive_does_not_restore_an_event_forgotten_after_selection(self) -> None:
        old_timestamp = time.time() - (45 * 86400)
        event_id = await self.store.add_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "task_id": "task-late-l1-archive",
                    "success": True,
                    "content": "Forget this event before archival resumes.",
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-late-l1-archive",
                timestamp=old_timestamp,
            )
        )
        await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="A summary makes the old event eligible for retention cleanup.",
                source_event_ids=[event_id],
            )
        )

        selected = asyncio.Event()
        resume = asyncio.Event()
        original_filter = self.store._filter_l1_retention_candidates

        async def pause_after_selection(event_ids: list[str]) -> list[str]:
            result = await original_filter(event_ids)
            selected.set()
            await resume.wait()
            return result

        with patch.object(
            self.store,
            "_filter_l1_retention_candidates",
            side_effect=pause_after_selection,
        ):
            maintenance = asyncio.create_task(
                self.store.cleanup_l1_data(
                    older_than_days=30,
                    history_behavior="archive",
                )
            )
            await asyncio.wait_for(selected.wait(), timeout=2)
            try:
                self.assertTrue(await self.store.forget_source_event(event_id))
            finally:
                resume.set()
            removed = await asyncio.wait_for(maintenance, timeout=2)

        self.assertEqual(removed["archived_events"], 0)
        self.assertEqual(removed["deleted_events"], 0)
        event = await self.store.l1.get_event(event_id)
        self.assertIsNotNone(event)
        self.assertIsNotNone(event["deleted_at"])

    async def test_l3_archive_does_not_restore_a_summary_forgotten_after_selection(self) -> None:
        old_timestamp = time.time() - (45 * 86400)
        event_id = await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "Forget the evidence before summary archival resumes.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-late-l3-archive",
                timestamp=old_timestamp,
            )
        )
        summary = await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="This old summary must not be archived after its source is forgotten.",
                source_event_ids=[event_id],
            ),
            summary_overrides={
                "period_start": old_timestamp,
                "period_end": old_timestamp,
                "created_at": old_timestamp,
                "updated_at": old_timestamp,
            },
        )

        selected = asyncio.Event()
        resume = asyncio.Event()
        original_list = self.store.l3.list_summaries_older_than

        async def pause_after_selection(*, older_than: float, limit: int = 1000):
            result = await original_list(older_than=older_than, limit=limit)
            selected.set()
            await resume.wait()
            return result

        with patch.object(
            self.store.l3,
            "list_summaries_older_than",
            side_effect=pause_after_selection,
        ):
            maintenance = asyncio.create_task(
                self.store.cleanup_l3_data(
                    older_than_days=30,
                    history_behavior="archive",
                )
            )
            await asyncio.wait_for(selected.wait(), timeout=2)
            try:
                self.assertTrue(await self.store.forget_source_event(event_id))
            finally:
                resume.set()
            removed = await asyncio.wait_for(maintenance, timeout=2)

        self.assertEqual(removed["archived_summaries"], 0)
        self.assertEqual(removed["deleted_summaries"], 0)
        self.assertIsNone(await self.store.l3.get_summary_by_id(summary["summary_id"]))

    async def test_cleanup_old_data_uses_configured_archive_directory(self) -> None:
        custom_archive_dir = self.base / "custom-archive"
        local_store = UnifiedMemoryStore(
            l1_db_path=str(self.base / "custom_archive_l1_events.db"),
            memory_db_path=str(self.base / "custom_archive_memory.db"),
            persist_dir=str(self.base / "custom_archive_memories"),
            archive_dir_path=str(custom_archive_dir),
            enable_l0=False,
            enable_l4=False,
            tuning=MemoryStoreTuning(
                enable_l1_vectors=False,
                enable_l2_vectors=False,
                enable_l3_vectors=False,
            ),
        )
        await local_store.initialize()
        try:
            old_timestamp = time.time() - (45 * 86400)
            linked_event_id = await local_store.add_event(
                Event(
                    type=EventTypes.TASK_COMPLETED,
                    data={
                        "user_id": "u1",
                        "session_id": "s1",
                        "task_id": "task-custom-archive",
                        "success": True,
                        "content": "Archived through a configured archive directory.",
                    },
                    source="worker",
                    level=EventLevel.INFO,
                    correlation_id="evt-custom-archive",
                    timestamp=old_timestamp,
                )
            )
            await local_store.l3.upsert_candidate(
                candidate=L3Candidate(
                    summary_type="insight",
                    summary_category="state_change",
                    content="A compressed reflection covers a custom archive event.",
                    source_event_ids=[linked_event_id],
                ),
                summary_overrides={
                    "period_start": old_timestamp,
                    "period_end": old_timestamp,
                    "created_at": old_timestamp,
                    "updated_at": old_timestamp,
                },
            )

            removed = await local_store.cleanup_old_data(
                older_than_days=30,
                history_behavior="archive",
            )

            self.assertEqual(removed["archived_events"], 1)
            self.assertEqual(removed["archived_summaries"], 1)
            archive_db_path = custom_archive_dir / time.strftime("%Y-%m-%d", time.gmtime())
            archive_db_path = archive_db_path.with_suffix(".db")
            self.assertTrue(archive_db_path.exists())
            self.assertFalse(
                (self.base / "custom_archive_memories" / "archive" / archive_db_path.name).exists()
            )
        finally:
            await local_store.shutdown()

    async def test_cleanup_old_data_deletes_expired_l3_summaries_without_touching_durable_events(self) -> None:
        old_timestamp = time.time() - (50 * 86400)
        durable_event_id = await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "Keep the durable fact but age out the hot reflection.",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-summary-retention-1",
                timestamp=old_timestamp,
            )
        )

        await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="An old reflection that should leave the active hot path.",
                source_event_ids=[durable_event_id],
            ),
            summary_overrides={
                "period_start": old_timestamp,
                "period_end": old_timestamp,
                "created_at": old_timestamp,
                "updated_at": old_timestamp,
            },
        )

        removed = await self.store.cleanup_old_data(older_than_days=30)

        self.assertEqual(removed["deleted_events"], 0)
        self.assertEqual(removed["deleted_summaries"], 1)
        self.assertEqual(await self.store.l3.count_summaries(), 0)
        self.assertIsNone((await self.store.l1.get_event(durable_event_id))["deleted_at"])

    async def test_l3_cleanup_keeps_reviewable_and_experience_summaries(self) -> None:
        old_timestamp = time.time() - (50 * 86400)
        event_id = await self.store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "Keep important review summaries."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-summary-protected-1",
                timestamp=old_timestamp,
            )
        )

        experience_summary = await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="episodic",
                content="An old experience recap should remain visible.",
                source_event_ids=[event_id],
                insight_metadata={"source_experience_id": "exp-protected"},
            ),
            summary_overrides={
                "period_start": old_timestamp,
                "period_end": old_timestamp,
                "created_at": old_timestamp,
                "updated_at": old_timestamp,
            },
        )
        confirmed_summary = await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="A confirmed insight should not expire as ordinary hot-path cache.",
                source_event_ids=[event_id],
                review_state="confirmed",
            ),
            summary_overrides={
                "period_start": old_timestamp + 1,
                "period_end": old_timestamp + 1,
                "created_at": old_timestamp + 1,
                "updated_at": old_timestamp + 1,
            },
        )

        removed = await self.store.cleanup_l3_data(older_than_days=30)

        self.assertEqual(removed["deleted_summaries"], 0)
        self.assertIsNotNone(await self.store.l3.get_summary_by_id(experience_summary["summary_id"]))
        self.assertIsNotNone(await self.store.l3.get_summary_by_id(confirmed_summary["summary_id"]))

    async def test_run_maintenance_leaves_l1_and_l3_cleanup_to_layer_schedules(self) -> None:
        old_timestamp = time.time() - (50 * 86400)
        linked_compressible_event_id = await self.store.add_event(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "task_id": "task-layer-split",
                    "success": True,
                    "content": "A compressible event covered by an old summary.",
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-layer-maintenance-split",
                timestamp=old_timestamp,
            )
        )

        await self.store.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="insight",
                summary_category="state_change",
                content="An old summary that should be handled by L3 maintenance.",
                source_event_ids=[linked_compressible_event_id],
            ),
            summary_overrides={
                "period_start": old_timestamp,
                "period_end": old_timestamp,
                "created_at": old_timestamp,
                "updated_at": old_timestamp,
            },
        )

        removed = await self.store.run_maintenance(retention_days=30)

        self.assertEqual(removed["deleted_events"], 0)
        self.assertEqual(removed["deleted_summaries"], 0)
        self.assertIsNone((await self.store.l1.get_event(linked_compressible_event_id))["deleted_at"])
        self.assertEqual(await self.store.l3.count_summaries(), 1)


class TestMemoryIntegrationModule(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)

        self.memory = UnifiedMemoryStore(
            l1_db_path=str(base / "l1_events.db"),
            memory_db_path=str(base / "memory.db"),
            persist_dir=str(base / "memories"),
            l2_batch_flush_interval_seconds=0,
            scenario_llm_pool=_FakeScenarioPool(_FakeAdapter(_STRESS_PHASE1, _STRESS_PHASE2)),
        )
        await self.memory.initialize()

        self.bus = InMemoryMessageBusBackend(num_workers=1)
        await self.bus.start()
        self.bus.bind_memory_operation_epoch(self.memory.memory_operation_epoch)

        self.integration = MemoryIntegrationModule(
            unified_memory=self.memory,
            message_bus=self.bus,
            config=MemoryIntegrationConfig(
                subscribed_events={
                    EventTypes.USER_MESSAGE,
                    EventTypes.TASK_COMPLETED,
                    "WORKER_AGENT_PROGRESS",
                },
            ),
        )
        await self.integration.start()

    async def asyncTearDown(self) -> None:
        await self.integration.stop()
        await self.bus.stop()
        await self.memory.shutdown()
        self.temp_dir.cleanup()

    async def test_event_pipeline_from_bus_does_not_implicitly_write_l0(self):
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
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "content": "I have been really stressed about work lately.",
                },
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

        async def _events_processed() -> bool:
            stats = self.integration.get_statistics()
            return stats["events_processed"] >= 3 and stats["l2_assertions_written"] >= 1

        await _wait_for_async_condition(
            _events_processed,
            timeout=2.0,
            interval=0.05,
        )

        stats = self.integration.get_statistics()
        workbench = await self.memory.l0.get_workbench("s1")
        l1_count = await self.memory.l1.count_events()

        self.assertGreaterEqual(stats["events_processed"], 3)
        self.assertEqual(l1_count, 2)
        self.assertIsNone(workbench["session"])
        self.assertEqual(workbench["attention_items"], [])
        self.assertGreaterEqual(stats["l2_assertions_written"], 1)

    async def test_pre_clear_runtime_event_backlog_does_not_repopulate_memory(self):
        blocker_started = asyncio.Event()
        blocker_release = asyncio.Event()

        async def _blocker(_event: Event) -> None:
            blocker_started.set()
            await blocker_release.wait()

        await self.bus.subscribe("BlockerEvent", _blocker)
        await self.bus.publish(Event(type="BlockerEvent", data={}))
        await asyncio.wait_for(blocker_started.wait(), timeout=1.0)

        await self.bus.publish(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "task_id": "before-clear",
                    "success": True,
                },
                source="runtime",
            )
        )
        await self.memory.clear_all_memory()

        blocker_release.set()
        self.assertIsNotNone(self.bus._queue)
        await asyncio.wait_for(self.bus._queue.join(), timeout=2.0)
        self.assertEqual(await self.memory.l1.count_events(), 0)

        await self.bus.publish(
            Event(
                type=EventTypes.TASK_COMPLETED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "task_id": "after-clear",
                    "success": True,
                },
                source="runtime",
            )
        )
        await asyncio.wait_for(self.bus._queue.join(), timeout=2.0)
        self.assertEqual(await self.memory.l1.count_events(), 1)


if __name__ == "__main__":
    unittest.main()
