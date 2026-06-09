"""Integration tests for L3/L4 triple-path RRF handlers.

Uses real L3SummaryStore / L4ProceduralMemoryStore with FTS5 (no vector)
to verify that BM25 + keyword paths and RRF fusion work end-to-end.
"""

from __future__ import annotations

import json
import time

import aiosqlite
import pytest

from magi.memory.hybrid_retrieval.handlers import L3Handler, L4Handler
from magi.memory.hybrid_retrieval.models import (
    L3Conditions,
    L4Conditions,
    RetrievalConfig,
    TimeRange,
)
from magi.memory.l3.summary_store import L3SummaryStore
from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
from magi.memory.hybrid_retrieval.fts_utils import tokenize_for_fts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_summary(store: L3SummaryStore, **overrides) -> dict:
    """Insert a summary directly via _store_summary."""
    now = time.time()
    summary = {
        "summary_id": overrides.get("summary_id", "sum-001"),
        "summary_type": overrides.get("summary_type", "daily"),
        "summary_category": overrides.get("summary_category", "general"),
        "period_start": overrides.get("period_start", now - 86400),
        "period_end": overrides.get("period_end", now),
        "content": overrides.get("content", "test summary content"),
        "key_topics": overrides.get("key_topics", []),
        "key_entities": overrides.get("key_entities", []),
        "sentiment_summary": overrides.get("sentiment_summary", "neutral"),
        "source_event_ids": overrides.get("source_event_ids", []),
        "source_event_count": overrides.get("source_event_count", 0),
        "importance_aggregate": overrides.get("importance_aggregate", 0.5),
        "event_type_distribution": overrides.get("event_type_distribution", {}),
        "generated_by_model": overrides.get("generated_by_model", "test"),
        "generation_prompt": overrides.get("generation_prompt", ""),
        "generation_reason": overrides.get("generation_reason", "test"),
        "created_at": overrides.get("created_at", now),
        "updated_at": overrides.get("updated_at", now),
    }
    await store._store_summary(summary)
    return summary


async def _seed_skill(store: L4ProceduralMemoryStore, **overrides) -> None:
    """Insert a skill directly via SQL + FTS sync."""
    now = time.time()
    skill_id = overrides.get("skill_id", "sk-001")
    skill_name = overrides.get("skill_name", "test_skill")
    skill_category = overrides.get("skill_category", "general")
    optimized_prompt = overrides.get("optimized_prompt", None)

    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                proficiency, total_attempts, success_count, failure_count,
                success_rate, source_event_ids, created_at, updated_at,
                optimized_prompt, circuit_breaker_state,
                circuit_breaker_failure_count, circuit_breaker_success_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill_id,
                skill_name,
                skill_category,
                overrides.get("skill_type", "tool"),
                overrides.get("proficiency", 0.5),
                overrides.get("total_attempts", 1),
                overrides.get("success_count", 1),
                overrides.get("failure_count", 0),
                overrides.get("success_rate", 1.0),
                json.dumps(overrides.get("source_event_ids", [])),
                overrides.get("created_at", now),
                overrides.get("updated_at", now),
                optimized_prompt,
                "closed",
                0,
                0,
            ),
        )
        # Sync FTS
        fts_content = f"{skill_name} {skill_category} {optimized_prompt or ''}"
        tokenized = tokenize_for_fts(fts_content)
        await db.execute("DELETE FROM l4_skills_fts WHERE skill_id = ?", (skill_id,))
        await db.execute(
            "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
            (skill_id, tokenized),
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def l3_store(tmp_path):
    return L3SummaryStore(db_path=str(tmp_path / "l3.db"), vector_enabled=False)


@pytest.fixture
def l4_store(tmp_path):
    return L4ProceduralMemoryStore(db_path=str(tmp_path / "l4.db"), vector_enabled=False)


# ---------------------------------------------------------------------------
# L3Handler triple-path integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestL3HandlerTriplePath:
    async def test_bm25_finds_summary(self, l3_store: L3SummaryStore) -> None:
        await l3_store.initialize()
        await _seed_summary(l3_store, summary_id="s-py", content="Python programming best practices")
        await _seed_summary(l3_store, summary_id="s-js", content="JavaScript frontend development")

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="Python", limit=10)
        results = await handler.execute(conds)

        ids = [r["summary_id"] for r in results]
        assert "s-py" in ids

    async def test_empty_query_returns_empty(self, l3_store: L3SummaryStore) -> None:
        await l3_store.initialize()
        await _seed_summary(l3_store, content="some content")

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []

    async def test_limit_respected(self, l3_store: L3SummaryStore) -> None:
        await l3_store.initialize()
        for i in range(10):
            await _seed_summary(l3_store, summary_id=f"s-{i:03d}", content=f"shared keyword topic {i}")

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="shared keyword", limit=3)
        results = await handler.execute(conds)
        assert len(results) <= 3

    async def test_summary_type_filter(self, l3_store: L3SummaryStore) -> None:
        await l3_store.initialize()
        await _seed_summary(l3_store, summary_id="s-daily", summary_type="daily", content="daily report analysis")
        await _seed_summary(l3_store, summary_id="s-weekly", summary_type="weekly", content="weekly report analysis")

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="report analysis", summary_types=["daily"], limit=10)
        results = await handler.execute(conds)

        ids = [r["summary_id"] for r in results]
        assert "s-daily" in ids
        # weekly should be filtered out by summary_type
        assert "s-weekly" not in ids

    async def test_summary_category_is_soft_preference_not_hard_filter(
        self, l3_store: L3SummaryStore
    ) -> None:
        """A mismatched ``summary_category`` must not drop matching content."""
        await l3_store.initialize()
        await _seed_summary(
            l3_store,
            summary_id="s-state",
            summary_type="insight",
            summary_category="state_change",
            content="stress pattern remained elevated",
        )
        await _seed_summary(
            l3_store,
            summary_id="s-trend",
            summary_type="insight",
            summary_category="trend_shift",
            content="stress pattern shifted toward recovery",
        )

        handler = L3Handler(l3_store)
        conds = L3Conditions(
            content_query="stress pattern",
            summary_types=["insight"],
            summary_categories=["state_change"],
            limit=10,
        )
        results = await handler.execute(conds)

        ids = [r["summary_id"] for r in results]
        assert "s-state" in ids
        assert "s-trend" in ids
        assert ids[0] == "s-state"

    async def test_time_range_filter(self, l3_store: L3SummaryStore) -> None:
        base = 1700000000.0
        await l3_store.initialize()
        await _seed_summary(
            l3_store, summary_id="s-old",
            content="old period summary data",
            period_start=base, period_end=base + 100,
        )
        await _seed_summary(
            l3_store, summary_id="s-new",
            content="new period summary data",
            period_start=base + 1000, period_end=base + 2000,
        )

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="summary data", limit=10)
        tr = TimeRange(start=base + 500, end=base + 3000)
        results = await handler.execute(conds, tr)

        ids = [r["summary_id"] for r in results]
        assert "s-new" in ids
        assert "s-old" not in ids

    async def test_no_match_returns_empty(self, l3_store: L3SummaryStore) -> None:
        await l3_store.initialize()
        await _seed_summary(l3_store, content="hello world")

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="quantumphysics", limit=10)
        results = await handler.execute(conds)
        assert results == []

    async def test_chinese_search(self, l3_store: L3SummaryStore) -> None:
        await l3_store.initialize()
        await _seed_summary(l3_store, summary_id="s-ml", content="机器学习模型训练优化方案")
        await _seed_summary(l3_store, summary_id="s-web", content="前端组件开发框架设计")

        handler = L3Handler(l3_store)
        conds = L3Conditions(content_query="机器学习", limit=10)
        results = await handler.execute(conds)

        ids = [r["summary_id"] for r in results]
        assert "s-ml" in ids


# ---------------------------------------------------------------------------
# L4Handler triple-path integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestL4HandlerTriplePath:
    async def test_bm25_finds_skill(self, l4_store: L4ProceduralMemoryStore) -> None:
        await l4_store.initialize()
        await _seed_skill(l4_store, skill_id="sk-deploy", skill_name="deploy_service", skill_category="ops",
                          optimized_prompt="Deploy application to production server")
        await _seed_skill(l4_store, skill_id="sk-test", skill_name="run_tests", skill_category="testing",
                          optimized_prompt="Run unit tests for the project")

        handler = L4Handler(l4_store)
        conds = L4Conditions(content_query="deploy", limit=10)
        results = await handler.execute(conds)

        ids = [r["skill_id"] for r in results]
        assert "sk-deploy" in ids

    async def test_empty_query_returns_empty(self, l4_store: L4ProceduralMemoryStore) -> None:
        await l4_store.initialize()
        await _seed_skill(l4_store, skill_name="some_skill")

        handler = L4Handler(l4_store)
        conds = L4Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []

    async def test_limit_respected(self, l4_store: L4ProceduralMemoryStore) -> None:
        await l4_store.initialize()
        for i in range(10):
            await _seed_skill(
                l4_store, skill_id=f"sk-{i:03d}",
                skill_name=f"shared_operation_{i}",
                skill_category="common",
            )

        handler = L4Handler(l4_store)
        conds = L4Conditions(content_query="shared_operation", limit=3)
        results = await handler.execute(conds)
        assert len(results) <= 3

    async def test_no_match_returns_empty(self, l4_store: L4ProceduralMemoryStore) -> None:
        await l4_store.initialize()
        await _seed_skill(l4_store, skill_name="hello_world")

        handler = L4Handler(l4_store)
        conds = L4Conditions(content_query="quantumphysics", limit=10)
        results = await handler.execute(conds)
        assert results == []

    async def test_chinese_search(self, l4_store: L4ProceduralMemoryStore) -> None:
        await l4_store.initialize()
        await _seed_skill(
            l4_store, skill_id="sk-ml",
            skill_name="机器学习训练",
            skill_category="ai",
            optimized_prompt="使用深度学习模型进行训练优化",
        )
        await _seed_skill(
            l4_store, skill_id="sk-web",
            skill_name="前端开发",
            skill_category="web",
            optimized_prompt="React组件开发和状态管理",
        )

        handler = L4Handler(l4_store)
        conds = L4Conditions(content_query="机器学习", limit=10)
        results = await handler.execute(conds)

        ids = [r["skill_id"] for r in results]
        assert "sk-ml" in ids

    async def test_keyword_matches_optimized_prompt(self, l4_store: L4ProceduralMemoryStore) -> None:
        await l4_store.initialize()
        await _seed_skill(
            l4_store, skill_id="sk-1",
            skill_name="generic_tool",
            skill_category="misc",
            optimized_prompt="Kubernetes cluster management and scaling",
        )

        handler = L4Handler(l4_store)
        conds = L4Conditions(content_query="Kubernetes", limit=10)
        results = await handler.execute(conds)

        ids = [r["skill_id"] for r in results]
        assert "sk-1" in ids

    async def test_config_passed_affects_fusion(self, l4_store: L4ProceduralMemoryStore) -> None:
        """Verify custom RetrievalConfig is used for RRF weights."""
        await l4_store.initialize()
        await _seed_skill(l4_store, skill_id="sk-a", skill_name="alpha_skill", skill_category="ops")

        config = RetrievalConfig(rrf_weight_bm25=2.0, rrf_weight_keyword=0.1)
        handler = L4Handler(l4_store, config=config)
        conds = L4Conditions(content_query="alpha", limit=10)
        results = await handler.execute(conds)
        # Should still find the skill — just verifying no crash with custom config
        assert len(results) >= 1
