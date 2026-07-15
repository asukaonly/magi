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

    fake_registry = MagicMock()
    async def fake_execute(name, args, ctx):
        return ToolResult(success=True, data="hello", execution_time=0.01)
    fake_registry.execute = fake_execute

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

    db_path = base / "memory.db"
    conn = sqlite3.connect(str(db_path))
    try:
        skills = conn.execute("SELECT COUNT(*) FROM procedural_skills").fetchone()[0]
        traces = conn.execute("SELECT COUNT(*) FROM l4_execution_traces").fetchone()[0]
    finally:
        conn.close()

    assert skills >= 1, f"procedural_skills should have a row, got {skills}"
    assert traces >= 1, f"l4_execution_traces should have a row, got {traces}"

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

    from magi.events.events import Event, EventTypes
    from magi.events.domain_payloads import TaskCompleted

    await bus.publish(Event(
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
    ))
    await asyncio.sleep(0.1)
    await subscriber.drain()

    conn = sqlite3.connect(str(base / "memory.db"))
    try:
        rows = conn.execute(
            "SELECT skill_name, skill_category FROM procedural_skills"
            " WHERE skill_category='workflow'"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) >= 1, "expected workflow-class skill row"

    await subscriber.stop()
    await store.shutdown()
    await bus.stop()
    tmp.cleanup()
