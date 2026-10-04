"""Tests for L4 execution traces recording and pruning."""
from __future__ import annotations

import json
from itertools import count
from types import SimpleNamespace
import time

import pytest

from magi.memory.l4.procedural_memory import (
    L4ProceduralMemoryStore,
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
async def store(tmp_path, monkeypatch):
    from magi.memory.l4.traces import store as trace_storage

    clock = count(1000)
    monkeypatch.setattr(trace_storage, "time", SimpleNamespace(time=lambda: float(next(clock))))
    s = L4ProceduralMemoryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await s.initialize()
    yield s


class TestExecutionTraceRecording:
    @pytest.mark.asyncio
    async def test_recorded_executions_keep_exact_identity_outcome_and_pending_count(self, store):
        events = [_make_action_event("web_search", success=(index % 2 == 0)) for index in range(5)]
        for index, event in enumerate(events):
            skill_id = await store.record_memory_event(event)
            assert skill_id is not None
            if index in (0, 2):
                skill = await store.get_skill(skill_name="web_search", skill_category="tool")
                assert skill["pending_trace_count"] == index + 1
        await store.record_memory_event(events[2])
        skill = await store.get_skill(skill_name="web_search", skill_category="tool")
        assert (
            skill["total_attempts"],
            skill["success_count"],
            skill["failure_count"],
            skill["pending_trace_count"],
        ) == (5, 3, 2, 5)
        traces = await store.get_recent_traces(skill_id)
        assert [(row["event_id"], row["skill_id"], row["success"]) for row in traces] == [
            (events[index].event_id, skill_id, index % 2 == 0) for index in [4, 3, 2, 1, 0]
        ]


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


class TestTracePruning:
    @pytest.mark.asyncio
    async def test_pruning_keeps_newest_exact_events_and_other_skill_history(self, store, monkeypatch):
        from magi.memory.l4.traces import store as trace_storage

        monkeypatch.setattr(trace_storage, "MAX_TRACES_PER_SKILL", 5)
        other = _make_action_event("other_tool")
        other_id = await store.record_memory_event(other)
        events = [_make_action_event("heavy_tool") for _ in range(8)]
        for event in events:
            skill_id = await store.record_memory_event(event)
        traces = await store.get_recent_traces(skill_id, limit=20)
        assert [row["event_id"] for row in traces] == [events[i].event_id for i in [7, 6, 5, 4, 3]]
        assert [row["event_id"] for row in await store.get_recent_traces(other_id)] == [other.event_id]
        skill = await store.get_skill(skill_name="heavy_tool", skill_category="tool")
        assert skill["total_attempts"] == 8
        assert skill["pending_trace_count"] == 5


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
    @pytest.mark.parametrize(
        "base,attempts,expected",
        [
            (5, 0, 5),
            (5, 3, 5),
            (5, 5, 5),
            (5, 20, 10),
            (5, 50, 15),
            (5, 100, 22),
            (5, 500, 50),
            (5, 2000, 50),
            (5, 100000, 50),
            (3, 10, 5),
            (7, 28, 14),
        ],
    )
    def test_extraction_threshold_scales_from_base_and_respects_retention_cap(
        self, base, attempts, expected
    ):
        assert L4ProceduralMemoryStore._adaptive_extraction_threshold(base, attempts) == expected


class TestStratifiedTraces:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "outcomes,limit,expected_indices",
        [
            ([False, False] + [True] * 18, 10, [19, 18, 17, 16, 15, 14, 13, 12, 1, 0]),
            ([True] * 10, 8, [9, 8, 7, 6, 5, 4, 3, 2]),
            ([True] * 20, 7, [19, 18, 17, 16, 15, 14, 13]),
            (
                [True, False, False, True, False, False, True, False, False, True],
                10,
                [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
            ),
        ],
        ids=["old-failures-survive", "only-success", "bounded-limit", "complete-no-duplicates"],
    )
    async def test_stratified_sample_has_exact_recent_outcomes_and_turns(
        self, store, outcomes, limit, expected_indices
    ):
        events = [
            _make_action_event(
                "sample_tool", success=success, turn_id=f"turn-{index}" if index % 2 == 0 else None
            )
            for index, success in enumerate(outcomes)
        ]
        for event in events:
            skill_id = await store.record_memory_event(event)
        await store.record_memory_event(
            _make_action_event("other_tool", success=False, turn_id="other-turn")
        )
        traces = await store._stratified_traces(skill_id, limit=limit)
        assert [(row["event_id"], row["success"], row["turn_id"]) for row in traces] == [
            (events[index].event_id, outcomes[index], events[index].turn_id)
            for index in expected_indices
        ]
        assert len({row["trace_id"] for row in traces}) == len(expected_indices)
        assert [row["created_at"] for row in traces] == [1000.0 + index for index in expected_indices]


# ---------------------------------------------------------------------------
# Turn-ID storage
# ---------------------------------------------------------------------------

class TestTurnIdStorage:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("turn_id", ["turn-abc-123", None], ids=["supplied", "absent"])
    async def test_recent_trace_preserves_exact_event_to_turn_mapping(self, store, turn_id):
        event = _make_action_event("tid_tool", turn_id=turn_id)
        skill_id = await store.record_memory_event(event)
        traces = await store.get_recent_traces(skill_id)
        assert [(row["event_id"], row["turn_id"]) for row in traces] == [(event.event_id, turn_id)]


# ---------------------------------------------------------------------------
# Duration baseline
# ---------------------------------------------------------------------------

class TestDurationBaseline:

    @pytest.mark.asyncio
    async def test_duration_baseline_uses_exact_units_and_retained_trace_percentile(self, store):
        for duration in [*range(1, 20), 1000]:
            skill_id = await store.record_memory_event(
                _make_action_event("dur_tool", metadata={"duration_ms": duration})
            )
        other_id = await store.record_memory_event(
            _make_action_event("other_tool", metadata={"duration_ms": 5000})
        )
        assert await store._get_duration_baseline(skill_id) == {"avg_ms": 59.5, "p95_ms": 19.0}
        assert await store._get_duration_baseline(other_id) == {"avg_ms": 5000.0, "p95_ms": 5000.0}
        assert await store._get_duration_baseline("missing-skill") == {}

        for _ in range(50):
            await store.record_memory_event(_make_action_event("dur_tool", metadata={"duration_ms": 5}))
        assert await store._get_duration_baseline(skill_id) == {
            "avg_ms": pytest.approx(144.0 / 7),
            "p95_ms": 5.0,
        }
        assert await store._get_duration_baseline(other_id) == {"avg_ms": 5000.0, "p95_ms": 5000.0}


# ---------------------------------------------------------------------------
# Recovery enrichment
# ---------------------------------------------------------------------------

class TestRecoveryEnrichment:

    @pytest.mark.asyncio
    async def test_recovery_is_the_first_successful_other_tool_in_the_same_turn(self, store):
        failed = _make_action_event("tool_a", success=False, turn_id="shared-turn")
        skill_id = await store.record_memory_event(failed)
        await store.record_memory_event(
            _make_action_event(
                "wrong_turn_early",
                turn_id="other-turn",
                metadata={"output": "unrelated early result"},
            )
        )
        await store.record_memory_event(
            _make_action_event("also_failed", success=False, turn_id="shared-turn")
        )
        await store.record_memory_event(
            _make_action_event(
                "tool_b", turn_id="shared-turn", metadata={"output": "fallback result"}
            )
        )
        await store.record_memory_event(
            _make_action_event(
                "tool_c", turn_id="shared-turn", metadata={"output": "later result"}
            )
        )
        await store.record_memory_event(
            _make_action_event(
                "wrong_turn_late",
                turn_id="other-turn",
                metadata={"output": "unrelated late result"},
            )
        )
        traces = await store.get_recent_traces(skill_id)
        await store._enrich_with_recovery(traces, skill_id)
        assert [(row["event_id"], row["recovery_tool"], row["recovery_output"]) for row in traces] == [
            (failed.event_id, "tool_b", "fallback result")
        ]

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
