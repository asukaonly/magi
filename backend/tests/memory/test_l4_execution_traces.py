"""Tests for L4 execution traces recording and pruning."""
from __future__ import annotations

import json
import time

import pytest

from magi.memory.l4.procedural_memory import (
    L4ProceduralMemoryStore,
    MAX_TRACES_PER_SKILL,
    DEFAULT_STRATEGY_EXTRACTION_THRESHOLD,
    _ADAPTIVE_MAX_THRESHOLD,
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
    turn_id: str | None = None,
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
        turn_id=turn_id,
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
        # Every stored execution is pending until its trace is consumed.
        assert skill["pending_trace_count"] == 3


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


class TestAdaptiveExtractionThreshold:
    def test_low_usage_keeps_base(self):
        result = L4ProceduralMemoryStore._adaptive_extraction_threshold(
            DEFAULT_STRATEGY_EXTRACTION_THRESHOLD, 3,
        )
        assert result == DEFAULT_STRATEGY_EXTRACTION_THRESHOLD

    def test_at_base_returns_base(self):
        result = L4ProceduralMemoryStore._adaptive_extraction_threshold(5, 5)
        assert result == 5

    def test_high_usage_scales_up(self):
        # 500 attempts with base 5: 5 * sqrt(500/5) = 5 * 10 = 50
        result = L4ProceduralMemoryStore._adaptive_extraction_threshold(5, 500)
        assert result == 50

    def test_very_high_usage_capped(self):
        result = L4ProceduralMemoryStore._adaptive_extraction_threshold(5, 100_000)
        assert result == min(_ADAPTIVE_MAX_THRESHOLD, MAX_TRACES_PER_SKILL)

    def test_never_below_base(self):
        # Even with tiny base, the returned value is at least the base.
        result = L4ProceduralMemoryStore._adaptive_extraction_threshold(3, 10)
        assert result >= 3

    def test_monotonically_increases(self):
        prev = 0
        for attempts in [5, 20, 50, 100, 500, 2000]:
            t = L4ProceduralMemoryStore._adaptive_extraction_threshold(5, attempts)
            assert t >= prev, f"threshold decreased at {attempts} attempts"
            prev = t


class TestStratifiedTraces:
    @pytest.mark.asyncio
    async def test_includes_both_successes_and_failures(self, store: L4ProceduralMemoryStore):
        """Even if mostly successes, stratified sampling includes failures."""
        # 18 successes + 2 failures
        for i in range(20):
            event = _make_action_event("bash", success=(i >= 2))
            await store.record_memory_event(event)
        skill = await store.get_skill(skill_name="bash", skill_category="tool")

        traces = await store._stratified_traces(skill["skill_id"], limit=10)
        assert len(traces) == 10
        failures = [t for t in traces if not t["success"]]
        successes = [t for t in traces if t["success"]]
        assert len(failures) >= 1, "should include at least one failure"
        assert len(successes) >= 1, "should include at least one success"

    @pytest.mark.asyncio
    async def test_all_same_outcome_still_works(self, store: L4ProceduralMemoryStore):
        """When all traces are successes, should still return traces."""
        for _ in range(10):
            await store.record_memory_event(_make_action_event("safe_tool", success=True))
        skill = await store.get_skill(skill_name="safe_tool", skill_category="tool")

        traces = await store._stratified_traces(skill["skill_id"], limit=8)
        assert len(traces) == 8
        assert all(t["success"] for t in traces)

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self, store: L4ProceduralMemoryStore):
        for _ in range(5):
            await store.record_memory_event(_make_action_event("ordered_tool"))
        skill = await store.get_skill(skill_name="ordered_tool", skill_category="tool")

        traces = await store._stratified_traces(skill["skill_id"], limit=5)
        timestamps = [t["created_at"] for t in traces]
        assert timestamps == sorted(timestamps, reverse=True)

    @pytest.mark.asyncio
    async def test_respects_limit(self, store: L4ProceduralMemoryStore):
        for _ in range(20):
            await store.record_memory_event(_make_action_event("many_tool"))
        skill = await store.get_skill(skill_name="many_tool", skill_category="tool")

        traces = await store._stratified_traces(skill["skill_id"], limit=7)
        assert len(traces) == 7

    @pytest.mark.asyncio
    async def test_no_duplicates(self, store: L4ProceduralMemoryStore):
        for i in range(10):
            await store.record_memory_event(_make_action_event("dup_tool", success=(i % 3 == 0)))
        skill = await store.get_skill(skill_name="dup_tool", skill_category="tool")

        traces = await store._stratified_traces(skill["skill_id"], limit=10)
        ids = [t["trace_id"] for t in traces]
        assert len(ids) == len(set(ids)), "found duplicate trace_ids"


# ---------------------------------------------------------------------------
# Turn-ID storage
# ---------------------------------------------------------------------------

class TestTurnIdStorage:
    @pytest.fixture()
    async def store(self, tmp_path) -> L4ProceduralMemoryStore:
        s = L4ProceduralMemoryStore(
            db_path=str(tmp_path / "memory.db"),
            vector_enabled=False,
        )
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_turn_id_persisted_in_trace(self, store: L4ProceduralMemoryStore):
        """Events with turn_id should have it stored in the trace row."""
        evt = _make_action_event("tid_tool", success=True, turn_id="turn-abc-123")
        await store.record_memory_event(evt)
        skill = await store.get_skill(skill_name="tid_tool", skill_category="tool")
        traces = await store.get_recent_traces(skill["skill_id"])
        assert len(traces) == 1
        assert traces[0]["turn_id"] == "turn-abc-123"

    @pytest.mark.asyncio
    async def test_turn_id_none_when_absent(self, store: L4ProceduralMemoryStore):
        """Events without turn_id produce traces with turn_id=None."""
        evt = _make_action_event("no_tid_tool", success=True)
        await store.record_memory_event(evt)
        skill = await store.get_skill(skill_name="no_tid_tool", skill_category="tool")
        traces = await store.get_recent_traces(skill["skill_id"])
        assert traces[0]["turn_id"] is None

    @pytest.mark.asyncio
    async def test_turn_id_in_stratified_traces(self, store: L4ProceduralMemoryStore):
        """Stratified trace output includes turn_id."""
        for i in range(5):
            evt = _make_action_event("strat_tid", success=True, turn_id=f"turn-{i}")
            await store.record_memory_event(evt)
        skill = await store.get_skill(skill_name="strat_tid", skill_category="tool")
        traces = await store._stratified_traces(skill["skill_id"], limit=5)
        for t in traces:
            assert "turn_id" in t
            assert t["turn_id"] is not None


# ---------------------------------------------------------------------------
# Duration baseline
# ---------------------------------------------------------------------------

class TestDurationBaseline:
    @pytest.fixture()
    async def store(self, tmp_path) -> L4ProceduralMemoryStore:
        s = L4ProceduralMemoryStore(
            db_path=str(tmp_path / "memory.db"),
            vector_enabled=False,
        )
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_returns_avg_and_p95(self, store: L4ProceduralMemoryStore):
        """After recording events, baseline should reflect stored stats."""
        meta = {"duration_ms": 100.0, "input_summary": "x"}
        for _ in range(3):
            await store.record_memory_event(
                _make_action_event("dur_tool", success=True, metadata=meta),
            )
        skill = await store.get_skill(skill_name="dur_tool", skill_category="tool")
        baseline = await store._get_duration_baseline(skill["skill_id"])
        assert "avg_ms" in baseline
        assert "p95_ms" in baseline
        assert baseline["avg_ms"] > 0

    @pytest.mark.asyncio
    async def test_missing_skill_returns_empty(self, store: L4ProceduralMemoryStore):
        """Non-existent skill_id returns empty dict."""
        baseline = await store._get_duration_baseline("nonexistent-skill-id")
        assert baseline == {}


# ---------------------------------------------------------------------------
# Recovery enrichment
# ---------------------------------------------------------------------------

class TestRecoveryEnrichment:
    @pytest.fixture()
    async def store(self, tmp_path) -> L4ProceduralMemoryStore:
        s = L4ProceduralMemoryStore(
            db_path=str(tmp_path / "memory.db"),
            vector_enabled=False,
        )
        await s.initialize()
        return s

    @pytest.mark.asyncio
    async def test_failure_annotated_with_recovery(self, store: L4ProceduralMemoryStore):
        """A failure in tool-A with same turn_id as success in tool-B gets annotated."""
        shared_turn = "turn-recovery-1"
        # Tool A fails
        await store.record_memory_event(
            _make_action_event("tool_a", success=False, turn_id=shared_turn),
        )
        # Tool B succeeds in same turn
        await store.record_memory_event(
            _make_action_event(
                "tool_b",
                success=True,
                turn_id=shared_turn,
                metadata={"output_summary": "fallback result"},
            ),
        )

        skill_a = await store.get_skill(skill_name="tool_a", skill_category="tool")
        traces = await store.get_recent_traces(skill_a["skill_id"])
        assert len(traces) == 1

        await store._enrich_with_recovery(traces, skill_a["skill_id"])
        assert traces[0].get("recovery_tool") == "tool_b"

    @pytest.mark.asyncio
    async def test_no_recovery_without_turn_id(self, store: L4ProceduralMemoryStore):
        """Failures without turn_id are not annotated."""
        await store.record_memory_event(
            _make_action_event("tool_c", success=False),
        )
        await store.record_memory_event(
            _make_action_event("tool_d", success=True),
        )

        skill_c = await store.get_skill(skill_name="tool_c", skill_category="tool")
        traces = await store.get_recent_traces(skill_c["skill_id"])
        await store._enrich_with_recovery(traces, skill_c["skill_id"])
        assert "recovery_tool" not in traces[0]

    @pytest.mark.asyncio
    async def test_no_self_recovery(self, store: L4ProceduralMemoryStore):
        """Recovery must come from a different skill."""
        shared_turn = "turn-self"
        await store.record_memory_event(
            _make_action_event("tool_e", success=False, turn_id=shared_turn),
        )
        # Same tool succeeds in same turn — should NOT be recovery
        await store.record_memory_event(
            _make_action_event("tool_e", success=True, turn_id=shared_turn),
        )

        skill_e = await store.get_skill(skill_name="tool_e", skill_category="tool")
        traces_fail = [
            t for t in await store.get_recent_traces(skill_e["skill_id"])
            if not t["success"]
        ]
        assert len(traces_fail) == 1
        await store._enrich_with_recovery(traces_fail, skill_e["skill_id"])
        assert "recovery_tool" not in traces_fail[0]

    @pytest.mark.asyncio
    async def test_success_traces_not_annotated(self, store: L4ProceduralMemoryStore):
        """Only failure traces should get recovery annotations."""
        shared_turn = "turn-ok"
        await store.record_memory_event(
            _make_action_event("tool_f", success=True, turn_id=shared_turn),
        )
        await store.record_memory_event(
            _make_action_event("tool_g", success=True, turn_id=shared_turn),
        )

        skill_f = await store.get_skill(skill_name="tool_f", skill_category="tool")
        traces = await store.get_recent_traces(skill_f["skill_id"])
        await store._enrich_with_recovery(traces, skill_f["skill_id"])
        assert "recovery_tool" not in traces[0]
