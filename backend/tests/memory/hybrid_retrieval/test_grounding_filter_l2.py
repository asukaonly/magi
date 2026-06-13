"""Tests for L2 relationship pruning in the grounding filter.

Mirrors test_grounding_filter.py exactly for the l2_relationships path.
Every failure mode (no bridge / disabled / LLM raises / timeout /
unparseable) must degrade to raw payload unchanged.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from magi.memory.hybrid_retrieval.grounding_filter import (
    GroundingFilter,
    MIN_CANDIDATES_TO_FILTER,
)
from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery


# ---------- minimal mocks (same shape as test_grounding_filter.py) ----------


class _StaticBridge:
    def __init__(self, response: str) -> None:
        self._response = response

    async def chat(self, **kwargs: Any) -> str:  # noqa: ARG002
        return self._response


class _RaisingBridge:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def chat(self, **kwargs: Any) -> str:  # noqa: ARG002
        raise self._exc


class _HangingBridge:
    async def chat(self, **kwargs: Any) -> str:  # noqa: ARG002
        await asyncio.sleep(30)
        return ""


def _make_relationships(n: int) -> list[dict[str, Any]]:
    """Build n fake L2 relationship dicts with the keys the real store returns."""
    return [
        {
            "subject_id": f"entity_{i:04d}",
            "object_id": f"entity_{i + 100:04d}",
            "predicate": "KNOWS" if i % 2 == 0 else "LIKES",
            "natural_summary": f"entity_{i:04d} 的关系描述 {i}",
            "subject_name": f"Entity {i}",
            "object_name": f"Entity {i + 100}",
            "confidence": 0.8,
            "updated_at": 1779944800 + i,
        }
        for i in range(n)
    ]


def _make_request(query: str = "我同事的老板是谁") -> RetrievalQuery:
    return RetrievalQuery(query=query, user_id="local_user")


# ---------- L2 relationship filtering: happy path ----------


@pytest.mark.asyncio
async def test_l2_keeps_relevant_relationship_and_drops_others() -> None:
    """Filter keeps the LLM-chosen relationship and drops the noise."""
    rels = _make_relationships(5)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [1, 3], "why": "only 1 and 3 are relevant"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 2
    assert out.l2_relationships[0]["subject_id"] == "entity_0000"
    assert out.l2_relationships[1]["subject_id"] == "entity_0002"


@pytest.mark.asyncio
async def test_l2_trace_records_applied_true_and_counts() -> None:
    rels = _make_relationships(10)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [2, 5], "why": "these two match"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    trace = out.trace["grounding_filter_l2"]
    assert trace["applied"] is True
    assert trace["input_count"] == 10
    assert trace["kept_count"] == 2
    assert trace["why"] == "these two match"


@pytest.mark.asyncio
async def test_l2_out_of_range_indices_silently_dropped() -> None:
    rels = _make_relationships(5)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [1, 999, 2], "why": "x"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    # 999 out of range → only 1 and 2 kept
    assert len(out.l2_relationships) == 2


@pytest.mark.asyncio
async def test_l2_explicit_empty_keep_clears_relationships() -> None:
    """LLM explicitly returns keep=[] for L2 — trust it, clear the list.

    Mirrors the l1_events behaviour: an explicit empty verdict is a VALID
    'none are relevant' judgment and must NOT be rolled back to raw.
    """
    rels = _make_relationships(10)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [], "why": "none relevant"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert out.l2_relationships == []
    trace = out.trace["grounding_filter_l2"]
    assert trace["applied"] is True
    assert trace["kept_count"] == 0
    assert trace.get("all_dropped") is True


@pytest.mark.asyncio
async def test_l2_all_out_of_range_indices_falls_back_not_cleared() -> None:
    """All indices are out of range (hallucination) → degrade, NOT clear."""
    rels = _make_relationships(3)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [99], "why": "x"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 3  # fell back, NOT cleared
    trace = out.trace["grounding_filter_l2"]
    assert trace["applied"] is False


# ---------- degradation paths — L2 relationships unchanged ----------


@pytest.mark.asyncio
async def test_l2_skips_trivial_count() -> None:
    """Fewer than MIN_CANDIDATES_TO_FILTER relationships — skip, no LLM call."""
    rels = _make_relationships(MIN_CANDIDATES_TO_FILTER - 1)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [1], "why": "x"}')  # must NOT be called
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == MIN_CANDIDATES_TO_FILTER - 1
    trace = out.trace.get("grounding_filter_l2") or {}
    assert trace.get("applied") is False
    assert trace.get("skipped_reason") == "trivial_count"


@pytest.mark.asyncio
async def test_l2_disabled_when_no_bridge() -> None:
    rels = _make_relationships(5)
    payload = RetrievalPayload(l2_relationships=rels)
    f = GroundingFilter(llm_bridge=None, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 5
    assert "grounding_filter_l2" not in out.trace


@pytest.mark.asyncio
async def test_l2_disabled_via_flag_even_with_bridge() -> None:
    rels = _make_relationships(5)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [1], "why": "x"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0, enabled=False)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 5
    assert "grounding_filter_l2" not in out.trace


@pytest.mark.asyncio
async def test_l2_llm_timeout_degrades_to_raw() -> None:
    rels = _make_relationships(10)
    payload = RetrievalPayload(l2_relationships=rels)
    f = GroundingFilter(llm_bridge=_HangingBridge(), timeout_seconds=0.05)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 10  # raw passed through
    trace = out.trace["grounding_filter_l2"]
    assert trace["applied"] is False
    assert trace["degraded_reason"] == "llm_timeout"


@pytest.mark.asyncio
async def test_l2_llm_exception_degrades_to_raw() -> None:
    rels = _make_relationships(10)
    payload = RetrievalPayload(l2_relationships=rels)
    f = GroundingFilter(
        llm_bridge=_RaisingBridge(RuntimeError("LLM exploded")),
        timeout_seconds=1.0,
    )
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 10
    trace = out.trace["grounding_filter_l2"]
    assert trace["applied"] is False
    assert "llm_exception" in trace["degraded_reason"]


@pytest.mark.asyncio
async def test_l2_malformed_response_degrades_to_raw() -> None:
    rels = _make_relationships(10)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge("definitely not JSON")
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == 10
    trace = out.trace["grounding_filter_l2"]
    assert trace["applied"] is False
    assert trace["degraded_reason"] == "bad_response_shape"


# ---------- L1 events UNAFFECTED by L2 filtering ----------


@pytest.mark.asyncio
async def test_l2_filter_does_not_touch_l1_events() -> None:
    """L2 relationship filtering must leave l1_events completely untouched."""
    l1 = [{"event_id": "ev_a", "content": "some event", "timestamp": 1.0}]
    rels = _make_relationships(5)
    payload = RetrievalPayload(l1_events=l1, l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [2], "why": "only 2 relevant"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    # L2 relationships filtered
    assert len(out.l2_relationships) == 1
    # L1 events completely unchanged (only one event, no l1 filter runs)
    assert len(out.l1_events) == 1
    assert out.l1_events[0]["event_id"] == "ev_a"


# ---------- prompt shape: natural_summary used as content field ----------


@pytest.mark.asyncio
async def test_l2_prompt_uses_natural_summary_as_content() -> None:
    """The L2 filter prompt must expose natural_summary so the LLM can
    judge relevance. A 'smart' bridge reads the prompt and verifies the
    natural_summary text appears in it."""
    rels = [
        {
            "subject_id": "user",
            "object_id": "boss_entity",
            "predicate": "REPORTS_TO",
            "natural_summary": "用户的同事 王明 向 陈总 汇报",
            "confidence": 0.9,
        },
        {
            "subject_id": "user",
            "object_id": "music_entity",
            "predicate": "LIKES",
            "natural_summary": "用户喜欢听周杰伦的歌",
            "confidence": 0.7,
        },
    ]
    payload = RetrievalPayload(l2_relationships=rels)

    class _InspectingBridge:
        """Bridge that checks the prompt contains the natural summaries."""
        captured_prompt: str = ""

        async def chat(self, **kwargs: Any) -> str:
            self.captured_prompt = kwargs["messages"][-1]["content"]
            # Only keep the relationship about 老板 (boss), not LIKES 周杰伦
            return '{"keep": [1], "why": "1 is about boss relationship"}'

    bridge = _InspectingBridge()
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request("我同事的老板是谁"))
    # The prompt must contain the natural summaries
    assert "王明" in bridge.captured_prompt
    assert "周杰伦" in bridge.captured_prompt
    # Filter correctly kept only the boss relationship
    assert len(out.l2_relationships) == 1
    assert out.l2_relationships[0]["predicate"] == "REPORTS_TO"
