"""Tests for L4 execution traces recording and pruning."""
from __future__ import annotations

import json
import time

import pytest

from magi.memory.l4.procedural_memory import (
    L4ProceduralMemoryStore,
    MAX_TRACES_PER_SKILL,
)
from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)


def _make_action_event(
    action_type: str = "test.action",
    success: bool = True,
    *,
    metadata: dict | None = None,
) -> MemoryEvent:
    now = time.time()
    # EventLevel: 0=DEBUG, 1=INFO, 2=WARNING, 3=ERROR, 4=CRITICAL
    # success is determined by level < 3 in L4.
    level = 1 if success else 3
    meta = metadata or {}
    return MemoryEvent(
        event_id=f"evt-{time.time_ns()}",
        correlation_id=f"corr-{time.time_ns()}",
        event_type="ActionExecuted",
        timestamp=now,
        created_at=now,
        source="worker",
        source_item_id=action_type,
        memory_domain=MemoryDomain.USER_AUTHORED,
        ingest_target=IngestTarget.L1_ONLY,
        cognition_eligible=True,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.COMPRESSIBLE,
        session_id=None,
        turn_id=None,
        user_id=None,
        task_id=None,
        content=json.dumps(
            {"action_type": action_type, "success": success},
            ensure_ascii=False,
        ),
        author_type="tool",
        content_type="tool_result",
        importance_score=0.5,
        level=level,
        metadata_json=meta,
    )


@pytest.fixture
async def store(tmp_path):
    s = L4ProceduralMemoryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await s.initialize()
    yield s


class TestExecutionTraceRecording:
    @pytest.mark.asyncio
    async def test_trace_created_on_new_skill(self, store: L4ProceduralMemoryStore):
        event = _make_action_event("web_search")
        skill_id = await store.record_memory_event(event)
        assert skill_id is not None

        traces = await store.get_recent_traces(skill_id)
        assert len(traces) == 1
        assert traces[0]["skill_id"] == skill_id
        assert traces[0]["success"] is True
        assert traces[0]["event_id"] == event.event_id

    @pytest.mark.asyncio
    async def test_trace_accumulates_on_updates(self, store: L4ProceduralMemoryStore):
        for i in range(5):
            event = _make_action_event("web_search", success=(i % 2 == 0))
            await store.record_memory_event(event)

        skill = await store.get_skill(skill_name="web_search", skill_category="tool")
        assert skill is not None
        traces = await store.get_recent_traces(skill["skill_id"])
        assert len(traces) == 5

    @pytest.mark.asyncio
    async def test_trace_captures_metadata(self, store: L4ProceduralMemoryStore):
        event = _make_action_event(
            "weather_api",
            success=False,
            metadata={
                "input": '{"city": "Beijing"}',
                "error": "HTTP 429 Too Many Requests",
                "duration_ms": 150.0,
                "task_category": "realtime_query",
            },
        )
        skill_id = await store.record_memory_event(event)
        traces = await store.get_recent_traces(skill_id)
        assert len(traces) == 1
        t = traces[0]
        assert t["success"] is False
        assert t["duration_ms"] == 150.0
        assert "429" in (t["error_summary"] or "")
        assert "Beijing" in (t["input_summary"] or "")
        assert t["task_context"] == "realtime_query"

    @pytest.mark.asyncio
    async def test_pending_trace_count_increments(self, store: L4ProceduralMemoryStore):
        for _ in range(3):
            await store.record_memory_event(_make_action_event("tool_a"))

        skill = await store.get_skill(skill_name="tool_a", skill_category="tool")
        assert skill is not None
        # First insert doesn't go through UPDATE path, but 2nd and 3rd do.
        # pending_trace_count starts at 0 for INSERT, then +1 for each UPDATE.
        assert skill["pending_trace_count"] == 2


class TestTracePruning:
    @pytest.mark.asyncio
    async def test_prune_keeps_max_traces(self, store: L4ProceduralMemoryStore):
        """Insert more than MAX_TRACES_PER_SKILL and verify pruning."""
        count = MAX_TRACES_PER_SKILL + 10
        for _ in range(count):
            await store.record_memory_event(_make_action_event("heavy_tool"))

        skill = await store.get_skill(skill_name="heavy_tool", skill_category="tool")
        traces = await store.get_recent_traces(skill["skill_id"], limit=count)
        assert len(traces) == MAX_TRACES_PER_SKILL


class TestClearIncludesTraces:
    @pytest.mark.asyncio
    async def test_clear_deletes_traces(self, store: L4ProceduralMemoryStore):
        await store.record_memory_event(_make_action_event("tool_x"))
        skill = await store.get_skill(skill_name="tool_x", skill_category="tool")

        cleared = await store.clear()
        assert cleared >= 1
        traces = await store.get_recent_traces(skill["skill_id"])
        assert len(traces) == 0
