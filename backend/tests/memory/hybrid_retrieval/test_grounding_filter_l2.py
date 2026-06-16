"""Tests for L2 relationship pruning in the unified grounding filter.

After the L1+L2 unification (single LLM call), L2 relationships and L1
events are judged together in one pass. This file covers:
  - L2-only payloads (l1_events empty)
  - Mixed payloads (both types present, one bridge call)
  - All degradation paths (no bridge / disabled / LLM raises / timeout /
    unparseable) — BOTH lists must be returned unchanged.
  - Obsolete independence test: the old "L2 fails, L1 still runs"
    property is intentionally dropped — one call means they degrade
    together. See the comment in test_unified_mixed_payload_single_bridge_call.

Every failure mode must degrade to raw payload unchanged.
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
        self.call_count = 0

    async def chat(self, **kwargs: Any) -> str:  # noqa: ARG002
        self.call_count += 1
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


def _make_events(n: int) -> list[dict[str, Any]]:
    return [
        {
            "event_id": f"ev_{i:04d}",
            "source": "screenshot_timeline",
            "content": f"OCR content row {i}",
            "timestamp": 1779944800 + i,
        }
        for i in range(n)
    ]


def _make_request(query: str = "我同事的老板是谁") -> RetrievalQuery:
    return RetrievalQuery(query=query, user_id="local_user")


# ---------- L2 relationship filtering: happy path ----------


@pytest.mark.asyncio
async def test_l2_keeps_relevant_relationship_and_drops_others() -> None:
    """Filter keeps the LLM-chosen relationship and drops the noise.

    With only l2_relationships in the payload, global indices 1..N map
    directly to relationships (no events before them).
    """
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
    """grounding_filter_l2 compat key records applied/input_count/kept_count."""
    rels = _make_relationships(10)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [2, 5], "why": "these two match"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    # Primary trace
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is True
    assert trace["input_count"] == 10
    assert trace["kept_count"] == 2
    assert trace["why"] == "these two match"
    # grounding_filter_l2 compat key
    l2_trace = out.trace["grounding_filter_l2"]
    assert l2_trace["applied"] is True
    assert l2_trace["input_count"] == 10
    assert l2_trace["kept_count"] == 2


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
    """LLM explicitly returns keep=[] for a payload of only relationships —
    trust it, clear the list.

    In unified mode, explicit empty verdict clears BOTH lists. With no
    l1_events in this payload the net effect on l2_relationships is the same.
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
    """Combined count (events + rels) below MIN_CANDIDATES_TO_FILTER — skip."""
    rels = _make_relationships(MIN_CANDIDATES_TO_FILTER - 1)
    payload = RetrievalPayload(l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [1], "why": "x"}')  # must NOT be called
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l2_relationships) == MIN_CANDIDATES_TO_FILTER - 1
    trace = out.trace.get("grounding_filter_l2") or {}
    assert trace.get("applied") is False
    assert trace.get("skipped_reason") == "trivial_count"
    assert bridge.call_count == 0


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


# ---------- unified mixed-payload: ONE bridge call, BOTH types filtered ----------


@pytest.mark.asyncio
async def test_unified_mixed_payload_single_bridge_call() -> None:
    """Core unified-design test: a payload with BOTH events AND relationships
    must be filtered with exactly ONE bridge call.

    Old independence property intentionally dropped: in the two-call design,
    an L2 failure left L1 untouched and vice versa. Now a single call
    covers both — a failure degrades BOTH lists together (pass-through).
    This is the accepted trade-off for halved latency.

    Global index layout: events first (1..n_events), relationships after
    (n_events+1..n_events+n_rels).
    """
    events = _make_events(3)  # global indices 1, 2, 3
    rels = _make_relationships(4)  # global indices 4, 5, 6, 7

    # Keep event idx=2 (ev_0001) and relationship idx=5 (entity_0001 LIKES)
    bridge = _StaticBridge('{"keep": [2, 5], "why": "event 2 and rel 5 match"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    payload = RetrievalPayload(l1_events=events, l2_relationships=rels)
    out = await f.apply(payload, _make_request("something"))

    # Exactly ONE bridge call
    assert bridge.call_count == 1

    # Correct event kept (global idx 2 → events[1])
    assert len(out.l1_events) == 1
    assert out.l1_events[0]["event_id"] == "ev_0001"

    # Correct relationship kept (global idx 5 → rels[5 - 3 - 1] = rels[1])
    assert len(out.l2_relationships) == 1
    assert out.l2_relationships[0]["subject_id"] == "entity_0001"

    # Trace reflects both counts
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is True
    assert trace["kept_events"] == 1
    assert trace["kept_relationships"] == 1
    assert trace["kept_count"] == 2
    assert trace["input_events"] == 3
    assert trace["input_relationships"] == 4


@pytest.mark.asyncio
async def test_unified_timeout_degrades_both_lists() -> None:
    """When the single LLM call times out, BOTH l1_events and
    l2_relationships must be returned unchanged."""
    events = _make_events(5)
    rels = _make_relationships(5)
    payload = RetrievalPayload(l1_events=events, l2_relationships=rels)
    f = GroundingFilter(llm_bridge=_HangingBridge(), timeout_seconds=0.05)
    out = await f.apply(payload, _make_request())
    # Both lists unchanged
    assert len(out.l1_events) == 5
    assert len(out.l2_relationships) == 5
    # Both trace keys record failure
    assert out.trace["grounding_filter"]["applied"] is False
    assert out.trace["grounding_filter"]["degraded_reason"] == "llm_timeout"
    assert out.trace["grounding_filter_l2"]["applied"] is False
    assert out.trace["grounding_filter_l2"]["degraded_reason"] == "llm_timeout"


@pytest.mark.asyncio
async def test_unified_explicit_empty_keep_clears_both_lists() -> None:
    """LLM returns keep=[] on a mixed payload → both lists cleared."""
    events = _make_events(3)
    rels = _make_relationships(3)
    payload = RetrievalPayload(l1_events=events, l2_relationships=rels)
    bridge = _StaticBridge('{"keep": [], "why": "nothing relevant"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert out.l1_events == []
    assert out.l2_relationships == []
    assert out.trace["grounding_filter"]["all_dropped"] is True
    assert out.trace["grounding_filter_l2"]["all_dropped"] is True


# ---------- prompt shape: natural_summary used as content field ----------


@pytest.mark.asyncio
async def test_l2_prompt_uses_natural_summary_as_content() -> None:
    """The unified filter prompt must expose natural_summary so the LLM can
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
