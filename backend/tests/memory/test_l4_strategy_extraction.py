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
    def test_round_trip_json(self):
        s = ExtractedStrategy(
            best_use_cases=["weather queries"],
            avoid_patterns=["vague locations"],
            recommended_approach="Use city name directly",
            context_preferences={"weather": 0.95},
            failure_patterns=["rate limiting"],
            confidence=0.8,
            extracted_from_traces=10,
            extracted_at=1700000000.0,
        )
        text = s.to_json()
        restored = ExtractedStrategy.from_json(text)
        assert restored.best_use_cases == ["weather queries"]
        assert restored.confidence == 0.8
        assert restored.context_preferences == {"weather": 0.95}

    def test_from_json_invalid(self):
        s = ExtractedStrategy.from_json("not json")
        assert s.confidence == 0.0
        assert s.best_use_cases == []

    def test_from_json_non_dict(self):
        s = ExtractedStrategy.from_json('"just a string"')
        assert s.confidence == 0.0


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

    def test_duration_baseline_rendered(self):
        prompt = _build_extraction_prompt(
            skill_name="slow_tool",
            skill_category="tool",
            total_attempts=5,
            success_rate=1.0,
            traces=[
                {"success": True, "duration_ms": 300.0},
            ],
            duration_baseline={"avg_ms": 200.0, "p95_ms": 400.0},
        )
        assert "Average duration: 200ms" in prompt
        assert "P95 duration: 400ms" in prompt

    def test_slow_flag_when_exceeds_p95(self):
        prompt = _build_extraction_prompt(
            skill_name="slow_tool",
            skill_category="tool",
            total_attempts=5,
            success_rate=0.5,
            traces=[
                {"success": True, "duration_ms": 500.0},   # > p95
                {"success": True, "duration_ms": 100.0},   # < p95
            ],
            duration_baseline={"avg_ms": 200.0, "p95_ms": 400.0},
        )
        assert "(SLOW)" in prompt
        # Only the first trace should be slow
        lines = prompt.split("\n")
        slow_lines = [line for line in lines if "(SLOW)" in line]
        assert len(slow_lines) == 1
        assert "500ms" in slow_lines[0]

    def test_no_slow_flag_without_baseline(self):
        prompt = _build_extraction_prompt(
            skill_name="tool",
            skill_category="tool",
            total_attempts=1,
            success_rate=1.0,
            traces=[
                {"success": True, "duration_ms": 9999.0},
            ],
        )
        assert "(SLOW)" not in prompt

    def test_recovery_rendered(self):
        prompt = _build_extraction_prompt(
            skill_name="flaky_tool",
            skill_category="tool",
            total_attempts=3,
            success_rate=0.5,
            traces=[
                {
                    "success": False,
                    "duration_ms": 100.0,
                    "error_summary": "connection reset",
                    "recovery_tool": "backup_tool",
                    "recovery_output": "fallback result OK",
                },
            ],
        )
        assert "→ Recovery: backup_tool succeeded" in prompt
        assert "fallback result OK" in prompt

    def test_no_recovery_line_for_success(self):
        prompt = _build_extraction_prompt(
            skill_name="ok_tool",
            skill_category="tool",
            total_attempts=1,
            success_rate=1.0,
            traces=[
                {"success": True, "duration_ms": 50.0},
            ],
        )
        assert "Recovery" not in prompt


class TestParseStrategyResponse:
    def test_valid_response(self):
        response = json.dumps({
            "best_use_cases": ["weather", "news"],
            "avoid_patterns": ["complex queries"],
            "recommended_approach": "Use specific keywords",
            "context_preferences": {"weather": 0.9, "news": 0.7},
            "failure_patterns": ["rate limit"],
            "confidence": 0.85,
        })
        strategy = _parse_strategy_response(response, trace_count=5)
        assert strategy.confidence == 0.85
        assert len(strategy.best_use_cases) == 2
        assert strategy.extracted_from_traces == 5
        assert strategy.extracted_at > 0

    def test_invalid_json(self):
        strategy = _parse_strategy_response("not json", trace_count=3)
        assert strategy.confidence == 0.0

    def test_clamps_confidence(self):
        response = json.dumps({"confidence": 1.5})
        strategy = _parse_strategy_response(response, trace_count=1)
        assert strategy.confidence == 1.0

    def test_truncates_lists(self):
        response = json.dumps({
            "best_use_cases": ["a", "b", "c", "d", "e"],
            "confidence": 0.5,
        })
        strategy = _parse_strategy_response(response, trace_count=1)
        assert len(strategy.best_use_cases) == 3  # max 3


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
        for i in range(threshold):
            await store.record_memory_event(
                _make_action_event("api_tool", success=(i % 3 != 0))
            )

        # Verify extraction was called
        store._strategy_extractor.extract_strategy.assert_called()

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

    @pytest.mark.asyncio
    async def test_no_extraction_without_llm(self, tmp_path):
        """Without LLM pool, extraction is silently skipped."""
        store = L4ProceduralMemoryStore(
            db_path=str(tmp_path / "memory.db"),
            vector_enabled=False,
            strategy_extraction_threshold=2,
        )
        await store.initialize()

        for _ in range(5):
            await store.record_memory_event(_make_action_event("tool_x"))

        skill = await store.get_skill(skill_name="tool_x", skill_category="tool")
        assert skill is not None
        # No extraction happened, optimization_score stays None
        assert skill["optimization_score"] is None
