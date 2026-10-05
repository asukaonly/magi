"""End-to-end: a tool invocation should land L4 procedural memory rows."""
from __future__ import annotations
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from magi.agent.execution.tool_invocation_service import (
    InvocationContext, ToolCall, ToolInvocationService,
)
from magi.core.container import get_container
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.events.domain_payloads import TaskContext
from magi.events.tracing import drain_pending
from magi.memory import UnifiedMemoryStore
from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber
from magi.tools.schema import ToolResult


@pytest.mark.asyncio
async def test_tool_invocation_lands_in_l4():
    bus = InMemoryMessageBusBackend()
    await bus.start()
    # Override the container INSTANCE: class-level overrides don't reach
    # the already-created singleton (providers are copied at instantiation).
    get_container().message_bus.override(bus)

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)

    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    bus.bind_memory_operation_epoch(store.memory_operation_epoch)

    subscriber = MemoryIngestionSubscriber(event_bus=bus, unified_memory=store)
    await subscriber.start()

    try:
        fake_registry = MagicMock()

        async def fake_execute(name, args, ctx):
            return ToolResult(success=True, data="hello", execution_time=0.01)

        fake_registry.execute = fake_execute

        from magi.events.events import EventTypes

        published = []

        async def capture(event):
            published.append(event)

        await bus.subscribe(EventTypes.SPAN_COMPLETED, capture)
        service = ToolInvocationService(fake_registry)

        await service.invoke(
            ToolCall(name="shell", args={"cmd": "echo hi"}),
            InvocationContext(
                tool_category="external_tool",
                task_context=TaskContext("sess-1", "turn-1", None, "user-1"),
                execution_context=MagicMock(task_id=None, agent_id="test-agent"),
            ),
        )

        # Drain async work: the bus subscriber spawns create_task tasks; give them
        # a moment, then drain explicitly.
        await drain_pending()
        await asyncio.sleep(0.05)
        await subscriber.drain()

        tool_events = [event for event in published if event.data.node_type == "tool_invocation"]
        assert len(tool_events) == 1
        await bus.publish(tool_events[0])
        await subscriber.drain()
        db_path = base / "memory.db"
        conn = sqlite3.connect(str(db_path))
        try:
            skills = conn.execute(
                "SELECT skill_id,skill_name,skill_category,total_attempts,success_count,failure_count,source_event_ids FROM procedural_skills"
            ).fetchall()
            traces = conn.execute(
                "SELECT skill_id,event_id,turn_id,success,input_summary,output_summary FROM l4_execution_traces"
            ).fetchall()
        finally:
            conn.close()

        import json

        assert len(skills) == 1 and len(traces) == 1
        skill_id, name, category, attempts, successes, failures, sources = skills[0]
        assert (name, category, attempts, successes, failures) == ("shell", "tool", 1, 1, 0)
        assert json.loads(sources) == [tool_events[0].event_id]
        assert traces[0][:4] == (skill_id, tool_events[0].event_id, "turn-1", 1)
        assert "echo hi" in traces[0][4]
        assert traces[0][5] == "hello"

    finally:
        await subscriber.stop()
        await store.shutdown()
        await bus.stop()
        get_container().message_bus.reset_override()
        tmp.cleanup()


@pytest.mark.asyncio
async def test_failed_tool_invocation_also_lands_with_failure_flag():
    bus = InMemoryMessageBusBackend()
    await bus.start()
    # Override the container INSTANCE: class-level overrides don't reach
    # the already-created singleton (providers are copied at instantiation).
    get_container().message_bus.override(bus)

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)

    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    bus.bind_memory_operation_epoch(store.memory_operation_epoch)

    subscriber = MemoryIngestionSubscriber(event_bus=bus, unified_memory=store)
    await subscriber.start()

    fake_registry = MagicMock()
    async def fake_execute_fail(name, args, ctx):
        return ToolResult(success=False, error="kaboom", error_code="X1", execution_time=0.001)
    fake_registry.execute = fake_execute_fail

    service = ToolInvocationService(fake_registry)

    await service.invoke(
        ToolCall(name="bad_tool", args={}),
        InvocationContext(
            tool_category="external_tool",
            task_context=TaskContext("sess-2", "turn-2", None, "user-2"),
            execution_context=MagicMock(task_id=None, agent_id="test-agent"),
        ),
    )

    await drain_pending()
    await asyncio.sleep(0.05)
    await subscriber.drain()

    conn = sqlite3.connect(str(base / "memory.db"))
    try:
        rows = conn.execute(
            "SELECT skill_name, failure_count, total_attempts FROM procedural_skills"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) >= 1
    skill_name, failure_count, total_attempts = rows[0]
    assert skill_name == "bad_tool"
    assert failure_count >= 1
    assert total_attempts >= 1

    await subscriber.stop()
    await store.shutdown()
    await bus.stop()
    get_container().message_bus.reset_override()
    tmp.cleanup()


@pytest.mark.asyncio
async def test_task_completed_event_lands_in_l4():
    bus = InMemoryMessageBusBackend()
    await bus.start()

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)

    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    bus.bind_memory_operation_epoch(store.memory_operation_epoch)

    subscriber = MemoryIngestionSubscriber(event_bus=bus, unified_memory=store)
    await subscriber.start()

    try:
        from magi.events.events import Event, EventTypes
        from magi.events.domain_payloads import TaskCompleted

        event = Event(
            type=EventTypes.TASK_COMPLETED,
            data=TaskCompleted(
                task_id="orch-1",
                task_type="chat",
                started_at=1.0,
                finished_at=2.0,
                summary="ok",
                context=TaskContext("s", "t", "orch-1", "u"),
            ),
            source="task_orchestrator",
        )
        await bus.publish(event)
        await asyncio.sleep(0.1)
        await subscriber.drain()

        conn = sqlite3.connect(str(base / "memory.db"))
        try:
            rows = conn.execute(
                "SELECT s.skill_name,s.skill_category,s.source_event_ids,t.event_id,t.turn_id,t.success,t.output_summary,t.task_context FROM procedural_skills s JOIN l4_execution_traces t ON t.skill_id=s.skill_id"
                " WHERE s.skill_category='workflow'"
            ).fetchall()
        finally:
            conn.close()

        import json

        assert len(rows) == 1
        name, category, sources, event_id, turn_id, success, summary, task_id = rows[0]
        assert (name, category, event_id, turn_id, success, summary, task_id) == (
            "orch-1",
            "workflow",
            event.event_id,
            "t",
            1,
            "ok",
            "orch-1",
        )
        assert json.loads(sources) == [event.event_id]

    finally:
        await subscriber.stop()
        await store.shutdown()
        await bus.stop()
        tmp.cleanup()
