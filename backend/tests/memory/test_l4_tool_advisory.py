"""Tests for L4 tool advisory API."""
from __future__ import annotations

import json
import time

import pytest

from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
from magi.memory.l4.strategy_extraction import ExtractedStrategy
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


@pytest.fixture
async def store(tmp_path):
    s = L4ProceduralMemoryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await s.initialize()
    yield s


class TestToolAdvisory:
    @pytest.mark.parametrize("tools", [[], ["nonexistent_tool"]])
    @pytest.mark.asyncio
    async def test_tools_without_retained_advice_return_empty(
        self, store: L4ProceduralMemoryStore, tools
    ):
        result = await store.get_tool_advisory(tools)
        assert result == []


    @pytest.mark.asyncio
    async def test_basic_advisory(self, store: L4ProceduralMemoryStore):
        # Record some successful executions
        for _ in range(3):
            await store.record_memory_event(_make_action_event("web_search", success=True))

        advisories = await store.get_tool_advisory(["web_search"])
        assert len(advisories) == 1
        adv = advisories[0]
        assert adv["tool_name"] == "web_search"
        assert adv["available"] is True
        assert adv["breaker_state"] == "closed"
        assert adv["success_rate"] == 1.0
        assert adv["total_attempts"] == 3
        assert adv["risk_note"] is None

    @pytest.mark.asyncio
    async def test_breaker_open_advisory(self, store: L4ProceduralMemoryStore):
        # Record 3 consecutive failures to trigger circuit breaker
        for _ in range(3):
            await store.record_memory_event(
                _make_action_event("flaky_api", success=False)
            )

        advisories = await store.get_tool_advisory(["flaky_api"])
        assert len(advisories) == 1
        adv = advisories[0]
        assert adv["available"] is False
        assert adv["breaker_state"] == "open"
        assert "open" in adv["risk_note"].lower()


    @pytest.mark.asyncio
    async def test_strategy_hint_from_json(self, store: L4ProceduralMemoryStore):
        # Create a skill with a strategy
        await store.record_memory_event(_make_action_event("weather_api"))
        skill = await store.get_skill(skill_name="weather_api", skill_category="tool")

        # Manually write a strategy
        strategy = ExtractedStrategy(
            best_use_cases=["direct weather queries"],
            recommended_approach="Pass city name in Chinese for best results",
            confidence=0.9,
        )
        await store._persist_strategy(
            skill_id=skill["skill_id"],
            strategy=strategy,
        )

        advisories = await store.get_tool_advisory(["weather_api"])
        assert len(advisories) == 1
        assert advisories[0]["strategy_hint"] == "Pass city name in Chinese for best results"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task_context,expected", [("weather queries", 0.95), (None, None), ("unrelated topic", None)]
    )
    async def test_context_fit_requires_a_matching_requested_context(
        self, store, task_context, expected
    ):
        await store.record_memory_event(_make_action_event("weather_api"))
        skill = await store.get_skill(skill_name="weather_api", skill_category="tool")
        await store._persist_strategy(
            skill_id=skill["skill_id"],
            strategy=ExtractedStrategy(
                context_preferences={"weather queries": 0.95, "geography": 0.6}, confidence=0.8
            ),
        )
        advisories = await store.get_tool_advisory(["weather_api"], task_context=task_context)
        assert len(advisories) == 1
        assert advisories[0]["context_fit"] == expected


    @pytest.mark.asyncio
    async def test_multiple_tools(self, store: L4ProceduralMemoryStore):
        await store.record_memory_event(_make_action_event("tool_a"))
        await store.record_memory_event(_make_action_event("tool_b"))

        advisories = await store.get_tool_advisory(["tool_a", "tool_b", "tool_c"])
        # tool_c has no history, should not appear
        assert len(advisories) == 2
        names = {a["tool_name"] for a in advisories}
        assert names == {"tool_a", "tool_b"}


class TestNotableAdvisories:
    """Tests for get_notable_advisories() — returns advisories without requiring
    the caller to supply tool names."""


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kind,outcomes,state,risk,hint",
        [
            (
                "open",
                [False, False, False],
                "open",
                "Circuit breaker open: consecutive failures detected",
                None,
            ),
            (
                "low_rate",
                [False, False, True, False],
                "closed",
                "Low success rate (25% over 4 attempts)",
                None,
            ),
            ("strategy", [True], "closed", None, "Use with JSON input"),
        ],
    )
    async def test_notable_advice_selects_independent_risks_and_excludes_healthy_tools(
        self, store, kind, outcomes, state, risk, hint
    ):
        assert await store.get_notable_advisories() == []
        for _ in range(3):
            await store.record_memory_event(_make_action_event("healthy_tool", success=True))
        for success in outcomes:
            await store.record_memory_event(_make_action_event(kind, success=success))
        if hint:
            skill = await store.get_skill(skill_name=kind, skill_category="tool")
            await store._persist_strategy(
                skill_id=skill["skill_id"],
                strategy=ExtractedStrategy(recommended_approach=hint, confidence=0.85),
            )
        result = await store.get_notable_advisories()
        assert [item["tool_name"] for item in result] == [kind]
        advisory = result[0]
        assert (
            advisory["breaker_state"],
            advisory["available"],
            advisory["risk_note"],
            advisory["strategy_hint"],
        ) == (state, state != "open", risk, hint)
        assert advisory["total_attempts"] == len(outcomes)
        assert advisory["success_rate"] == pytest.approx(sum(outcomes) / len(outcomes))
        assert await store.get_tool_advisory([kind]) == result


    @pytest.mark.asyncio
    async def test_limit_respected(self, store: L4ProceduralMemoryStore):
        # Create 5 tools with open breakers
        for i in range(5):
            for _ in range(3):
                await store.record_memory_event(
                    _make_action_event(f"tool_{i}", success=False)
                )
        result = await store.get_notable_advisories(limit=2)
        assert len(result) == 2
