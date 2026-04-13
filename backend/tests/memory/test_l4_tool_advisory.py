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
    @pytest.mark.asyncio
    async def test_empty_tool_list(self, store: L4ProceduralMemoryStore):
        result = await store.get_tool_advisory([])
        assert result == []

    @pytest.mark.asyncio
    async def test_unknown_tools_return_nothing(self, store: L4ProceduralMemoryStore):
        result = await store.get_tool_advisory(["nonexistent_tool"])
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
    async def test_low_success_rate_risk(self, store: L4ProceduralMemoryStore):
        # 1 success, 3 failures
        await store.record_memory_event(_make_action_event("unreliable", success=True))
        for _ in range(3):
            await store.record_memory_event(
                _make_action_event("unreliable", success=False)
            )

        advisories = await store.get_tool_advisory(["unreliable"])
        assert len(advisories) == 1
        adv = advisories[0]
        assert adv["risk_note"] is not None
        assert "success rate" in adv["risk_note"].lower() or "open" in adv["risk_note"].lower()

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
    async def test_context_fit_matching(self, store: L4ProceduralMemoryStore):
        await store.record_memory_event(_make_action_event("weather_api"))
        skill = await store.get_skill(skill_name="weather_api", skill_category="tool")

        strategy = ExtractedStrategy(
            context_preferences={"weather queries": 0.95, "geography": 0.6},
            confidence=0.8,
        )
        await store._persist_strategy(skill_id=skill["skill_id"], strategy=strategy)

        advisories = await store.get_tool_advisory(
            ["weather_api"], task_context="weather queries"
        )
        assert len(advisories) == 1
        assert advisories[0]["context_fit"] == 0.95

    @pytest.mark.asyncio
    async def test_context_fit_none_without_context(self, store: L4ProceduralMemoryStore):
        await store.record_memory_event(_make_action_event("tool_a"))
        advisories = await store.get_tool_advisory(["tool_a"])
        assert len(advisories) == 1
        assert advisories[0]["context_fit"] is None

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
    async def test_empty_store(self, store: L4ProceduralMemoryStore):
        result = await store.get_notable_advisories()
        assert result == []

    @pytest.mark.asyncio
    async def test_healthy_tools_excluded(self, store: L4ProceduralMemoryStore):
        """Tools with closed breaker, no strategy, and high success rate should NOT appear."""
        for _ in range(3):
            await store.record_memory_event(_make_action_event("healthy_tool", success=True))
        result = await store.get_notable_advisories()
        assert all(a["tool_name"] != "healthy_tool" for a in result)

    @pytest.mark.asyncio
    async def test_breaker_open_included(self, store: L4ProceduralMemoryStore):
        for _ in range(3):
            await store.record_memory_event(_make_action_event("broken_tool", success=False))
        result = await store.get_notable_advisories()
        names = {a["tool_name"] for a in result}
        assert "broken_tool" in names
        adv = next(a for a in result if a["tool_name"] == "broken_tool")
        assert adv["available"] is False

    @pytest.mark.asyncio
    async def test_strategy_present_included(self, store: L4ProceduralMemoryStore):
        await store.record_memory_event(_make_action_event("smart_tool", success=True))
        skill = await store.get_skill(skill_name="smart_tool", skill_category="tool")
        strategy = ExtractedStrategy(
            recommended_approach="Use with JSON input",
            confidence=0.85,
        )
        await store._persist_strategy(skill_id=skill["skill_id"], strategy=strategy)
        result = await store.get_notable_advisories()
        names = {a["tool_name"] for a in result}
        assert "smart_tool" in names
        adv = next(a for a in result if a["tool_name"] == "smart_tool")
        assert adv["strategy_hint"] == "Use with JSON input"

    @pytest.mark.asyncio
    async def test_low_success_rate_included(self, store: L4ProceduralMemoryStore):
        await store.record_memory_event(_make_action_event("shaky_tool", success=True))
        for _ in range(3):
            await store.record_memory_event(_make_action_event("shaky_tool", success=False))
        result = await store.get_notable_advisories()
        names = {a["tool_name"] for a in result}
        assert "shaky_tool" in names

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
