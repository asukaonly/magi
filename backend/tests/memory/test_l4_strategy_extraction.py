"""Tests for L4 strategy extraction logic."""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.l4.strategy_extraction import (
    ExtractedStrategy,
    _build_extraction_prompt,
    _parse_strategy_response,
)
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
    metadata: dict | None = None,
) -> MemoryEvent:
    now = time.time()
    level = 1 if success else 3
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
        content=json.dumps({"action_type": action_type, "success": success}),
        author_type="tool",
        content_type="tool_result",
        importance_score=0.5,
        level=level,
        metadata_json=metadata,
    )


class TestExtractedStrategy:
    def test_strategy_serialization_preserves_every_published_field(self):
        from dataclasses import asdict

        expected = {
            "best_use_cases": ["weather queries"],
            "avoid_patterns": ["vague locations"],
            "recommended_approach": "Use city name directly",
            "context_preferences": {"weather": 0.95},
            "failure_patterns": ["rate limiting"],
            "confidence": 0.8,
            "extracted_from_traces": 10,
            "extracted_at": 1700000000.0,
        }
        encoded = ExtractedStrategy(**expected).to_json()
        assert json.loads(encoded) == expected
        assert asdict(ExtractedStrategy.from_json(json.dumps(expected))) == expected

    @pytest.mark.parametrize("payload", ["not json", '"just a string"', "[]", "null"])
    def test_invalid_strategy_envelopes_decode_to_complete_empty_contract(self, payload):
        from dataclasses import asdict

        expected = {
            "best_use_cases": [],
            "avoid_patterns": [],
            "recommended_approach": "",
            "context_preferences": {},
            "failure_patterns": [],
            "confidence": 0.0,
            "extracted_from_traces": 0,
            "extracted_at": 0.0,
        }
        assert asdict(ExtractedStrategy.from_json(payload)) == expected
        assert asdict(_parse_strategy_response(payload, trace_count=3)) == expected


class TestBuildExtractionPrompt:
    def test_includes_skill_info(self):
        prompt = _build_extraction_prompt(
            skill_name="web_search",
            skill_category="tool",
            total_attempts=10,
            success_rate=0.8,
            traces=[
                {
                    "success": True,
                    "duration_ms": 200.0,
                    "task_context": "realtime_query",
                    "input_summary": "query=weather",
                    "output_summary": "sunny",
                    "error_summary": None,
                },
                {
                    "success": False,
                    "duration_ms": 500.0,
                    "task_context": "research",
                    "input_summary": "query=complex topic",
                    "output_summary": None,
                    "error_summary": "timeout",
                },
            ],
        )
        assert "web_search" in prompt
        assert "80%" in prompt
        assert "SUCCESS" in prompt
        assert "FAILURE" in prompt
        assert "timeout" in prompt


    @pytest.mark.parametrize(
        "baseline,slow", [(None, False), ({"avg_ms": 200.0, "p95_ms": 400.0}, True)]
    )
    def test_slow_label_requires_a_baseline_and_strictly_exceeds_its_p95(self, baseline, slow):
        prompt = _build_extraction_prompt(
            skill_name="tool",
            skill_category="tool",
            total_attempts=3,
            success_rate=1.0,
            traces=[
                {"success": True, "duration_ms": 500.0},
                {"success": True, "duration_ms": 400.0},
                {"success": True, "duration_ms": 100.0},
            ],
            duration_baseline=baseline,
        )
        trace_lines = [
            line for line in prompt.splitlines() if line.startswith("#") and "[SUCCESS]" in line
        ]
        assert len(trace_lines) == 3
        assert ["(SLOW)" in line for line in trace_lines] == [slow, False, False]
        if baseline:
            assert "Average duration: 200ms, P95 duration: 400ms" in prompt


    @pytest.mark.parametrize("success", [False, True])
    def test_recovery_enrichment_reaches_the_prompt_only_for_failed_traces(self, success):
        from magi.memory.l4.traces.analysis import apply_recovery_annotations

        traces = [{"success": success, "duration_ms": 100.0, "turn_id": "shared-turn"}]
        apply_recovery_annotations(
            traces,
            {"shared-turn": {"recovery_tool": "backup_tool", "recovery_output": "fallback result OK"}},
        )
        prompt = _build_extraction_prompt(
            skill_name="flaky_tool",
            skill_category="tool",
            total_attempts=1,
            success_rate=float(success),
            traces=traces,
        )
        assert ("→ Recovery: backup_tool succeeded with: fallback result OK" in prompt) is (not success)
        assert ("Recovery" not in prompt) is success


class TestParseStrategyResponse:
    @pytest.mark.parametrize("extra", [False, True])
    def test_strategy_response_preserves_fields_and_ordered_list_limits(self, monkeypatch, extra):
        from dataclasses import asdict
        from types import SimpleNamespace

        monkeypatch.setattr(
            "magi.memory.l4.strategy_extraction.time", SimpleNamespace(time=lambda: 1700000000.0)
        )
        payload = {
            "best_use_cases": ["weather", "news", "research"],
            "avoid_patterns": ["vague query", "missing region", "stale date"],
            "recommended_approach": "Use specific keywords",
            "context_preferences": {"weather": 0.9, "news": 0.7},
            "failure_patterns": ["rate limit", "timeout", "empty output"],
            "confidence": 0.85,
        }
        if extra:
            for key in ["best_use_cases", "avoid_patterns", "failure_patterns"]:
                payload[key] += ["discard fourth", "discard fifth"]
        strategy = _parse_strategy_response(json.dumps(payload), trace_count=5)
        assert asdict(strategy) == {
            "best_use_cases": ["weather", "news", "research"],
            "avoid_patterns": ["vague query", "missing region", "stale date"],
            "recommended_approach": "Use specific keywords",
            "context_preferences": {"weather": 0.9, "news": 0.7},
            "failure_patterns": ["rate limit", "timeout", "empty output"],
            "confidence": 0.85,
            "extracted_from_traces": 5,
            "extracted_at": 1700000000.0,
        }


    def test_clamps_confidence(self):
        response = json.dumps({"confidence": 1.5})
        strategy = _parse_strategy_response(response, trace_count=1)
        assert strategy.confidence == 1.0


class TestStrategyExtractionIntegration:
    @pytest.mark.asyncio
    async def test_extraction_triggers_after_threshold(self, tmp_path):
        """Strategy extraction triggers after N traces on same skill."""
        threshold = 3

        mock_pool = MagicMock()

        store = L4ProceduralMemoryStore(
            db_path=str(tmp_path / "memory.db"),
            vector_enabled=False,
            scenario_llm_pool=mock_pool,
            strategy_extraction_threshold=threshold,
        )
        await store.initialize()

        # Patch the extractor's extract_strategy to return a canned strategy
        mock_strategy = ExtractedStrategy(
            best_use_cases=["test scenario"],
            recommended_approach="just do it",
            context_preferences={"test": 0.9},
            confidence=0.75,
            extracted_from_traces=5,
            extracted_at=time.time(),
        )
        store._strategy_extractor = MagicMock()
        store._strategy_extractor.extract_strategy = AsyncMock(return_value=mock_strategy)

        # Record exactly the threshold of independent executions.
        events = []
        for i in range(threshold):
            event = _make_action_event("api_tool", success=(i % 3 != 0))
            events.append(event)
            await store.record_memory_event(event)
            if i < threshold - 1:
                store._strategy_extractor.extract_strategy.assert_not_awaited()
                pending = await store.get_skill(skill_name="api_tool", skill_category="tool")
                assert pending["pending_trace_count"] == i + 1

        # Verify extraction was called
        store._strategy_extractor.extract_strategy.assert_awaited_once()
        request = store._strategy_extractor.extract_strategy.await_args.kwargs
        assert request["skill_name"] == "api_tool"
        assert request["skill_category"] == "tool"
        assert request["total_attempts"] == 3
        assert request["success_rate"] == pytest.approx(2 / 3)
        assert {trace["event_id"]: trace["success"] for trace in request["traces"]} == {
            event.event_id: (index != 0) for index, event in enumerate(events)
        }
        assert len(request["traces"]) == 3

        # Verify strategy was persisted
        skill = await store.get_skill(skill_name="api_tool", skill_category="tool")
        assert skill is not None
        assert skill["optimization_score"] == 0.75
        # pending_trace_count should be reset to 0 after extraction
        assert skill["pending_trace_count"] == 0

        # Verify optimized_prompt now contains strategy JSON
        strategy = ExtractedStrategy.from_json(skill["optimized_prompt"])
        assert strategy.best_use_cases == ["test scenario"]
        assert strategy.confidence == 0.75

        from dataclasses import asdict

        assert asdict(strategy) == asdict(mock_strategy)
        await store.record_memory_event(_make_action_event("api_tool"))
        store._strategy_extractor.extract_strategy.assert_awaited_once()
        assert (await store.get_skill(skill_name="api_tool", skill_category="tool"))[
            "pending_trace_count"
        ] == 1

    @pytest.mark.asyncio
    async def test_no_extraction_without_llm(self, tmp_path, monkeypatch):
        """Without LLM pool, extraction is silently skipped."""
        extractor = AsyncMock()
        monkeypatch.setattr(
            "magi.memory.l4.strategy_extraction.L4StrategyExtractor.extract_strategy", extractor
        )
        store = L4ProceduralMemoryStore(
            db_path=str(tmp_path / "memory.db"),
            vector_enabled=False,
            strategy_extraction_threshold=2,
        )
        await store.initialize()

        events = [_make_action_event("tool_x") for _ in range(5)]
        for event in events:
            await store.record_memory_event(event)

        skill = await store.get_skill(skill_name="tool_x", skill_category="tool")
        assert skill is not None
        # No extraction happened, optimization_score stays None
        assert skill["optimization_score"] is None

        extractor.assert_not_awaited()
        assert skill["pending_trace_count"] == 5
        assert json.loads(skill["optimized_prompt"]) == {"action_type": "tool_x", "success": True}
        traces = await store.get_recent_traces(skill["skill_id"])
        assert {trace["event_id"] for trace in traces} == {event.event_id for event in events}
