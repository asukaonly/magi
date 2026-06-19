"""Tests for the post-retrieval grounding filter.

The filter is an OPTIONAL layer that trims raw retrieval candidates
down to what an LLM agrees is relevant before they're handed to the
answer LLM. Every failure mode must degrade to "raw payload passes
through" — never block retrieval.

After the L1+L2 unification, one LLM call judges ALL candidates
(events + relationships) together. This file covers the L1 event
path; test_grounding_filter_l2.py covers L2 and mixed payloads.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.grounding_filter import (
    CONTENT_CAP_CHARS,
    GroundingFilter,
    MIN_CANDIDATES_TO_FILTER,
    _SYSTEM_PROMPT,
    _build_prompt_payload,
    _parse_keep_response,
)
from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery


# ---------- minimal mocks ----------


class _StaticBridge:
    """Mock LLM bridge — returns a canned response string."""

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


def _make_events(n: int) -> list[dict[str, Any]]:
    return [
        {
            "event_id": f"ev_{i:04d}",
            "source": "screenshot_timeline",
            "content": f"OCR content row {i}, ABC keyword",
            "timestamp": 1779944800 + i,
        }
        for i in range(n)
    ]


def _make_request(query: str = "what about ABC") -> RetrievalQuery:
    return RetrievalQuery(query=query, user_id="local_user")


# ---------- response parsing ----------


def test_parse_extracts_keep_array_and_why() -> None:
    raw = '{"keep": [1, 3, 5], "why": "matched ABC keyword"}'
    keep, why = _parse_keep_response(raw)
    assert keep == [1, 3, 5]
    assert why == "matched ABC keyword"


def test_parse_tolerates_prose_around_json() -> None:
    raw = 'Sure! Here is the result:\n{"keep": [2], "why": "x"}\nDone.'
    keep, why = _parse_keep_response(raw)
    assert keep == [2]
    assert why == "x"


def test_parse_coerces_string_integers() -> None:
    """LLM sometimes emits indices as strings."""
    raw = '{"keep": ["1", "4"], "why": "y"}'
    keep, _ = _parse_keep_response(raw)
    assert keep == [1, 4]


def test_parse_returns_none_on_malformed_input() -> None:
    assert _parse_keep_response("not json at all")[0] is None
    assert _parse_keep_response('{"no_keep_field": true}')[0] is None
    assert _parse_keep_response("")[0] is None


def test_parse_drops_booleans_in_keep() -> None:
    """bool is a subclass of int in Python — must not be mistaken
    for an index."""
    raw = '{"keep": [true, false, 2], "why": ""}'
    keep, _ = _parse_keep_response(raw)
    assert keep == [2]


# ---------- end-to-end behaviour ----------


@pytest.mark.asyncio
async def test_skips_trivial_count_below_min_candidates() -> None:
    """0 or 1 combined candidate — not worth an LLM round-trip."""
    events = _make_events(MIN_CANDIDATES_TO_FILTER - 1)  # 0 or 1 event, no rels
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge('{"keep": [1], "why": "x"}')  # must NOT be called
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    # All events still present.
    assert len(out.l1_events) == MIN_CANDIDATES_TO_FILTER - 1
    trace = out.trace.get("grounding_filter") or {}
    assert trace.get("applied") is False
    assert trace.get("skipped_reason") == "trivial_count"
    assert bridge.call_count == 0


@pytest.mark.asyncio
async def test_makes_exactly_one_bridge_call() -> None:
    """Unified filter must make exactly ONE bridge call per apply(), not two."""
    events = _make_events(5)
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge('{"keep": [1, 2], "why": "match"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    await f.apply(payload, _make_request())
    assert bridge.call_count == 1


@pytest.mark.asyncio
async def test_filters_to_kept_indices() -> None:
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    # 1-based indices.
    bridge = _StaticBridge('{"keep": [1, 5, 10], "why": "match"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 3
    assert out.l1_events[0]["event_id"] == "ev_0000"
    assert out.l1_events[1]["event_id"] == "ev_0004"
    assert out.l1_events[2]["event_id"] == "ev_0009"
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is True
    assert trace["input_count"] == 20
    assert trace["kept_count"] == 3
    assert trace["why"] == "match"


@pytest.mark.asyncio
async def test_out_of_range_indices_are_silently_dropped() -> None:
    events = _make_events(15)
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge('{"keep": [1, 999, 2], "why": "x"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    # 999 dropped; 1 and 2 kept.
    assert len(out.l1_events) == 2


@pytest.mark.asyncio
async def test_explicit_empty_keep_clears_l1_events() -> None:
    """LLM explicitly returns keep=[] — a VALID 'none are relevant'
    verdict. The filter should TRUST it and clear l1_events, NOT fall
    back to raw (which would restore the noise the LLM correctly
    judged irrelevant).

    In unified mode, empty keep clears BOTH lists. With no relationships
    in this payload, the net effect on l1_events is the same."""
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge('{"keep": [], "why": "none relevant"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert out.l1_events == []  # LLM verdict trusted, NOT rolled back
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is True
    assert trace["kept_count"] == 0
    assert trace.get("all_dropped") is True


@pytest.mark.asyncio
async def test_all_out_of_range_indices_fall_back_not_cleared() -> None:
    """LLM returns non-empty keep but every index is out of range —
    this is a hallucination, not a clean 'none relevant' verdict.
    Should fall back to raw (NOT clear l1_events)."""
    events = _make_events(2)
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge('{"keep": [99], "why": "x"}')  # index past list end
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 2  # fell back, NOT cleared
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is False


@pytest.mark.asyncio
async def test_llm_timeout_degrades_to_raw() -> None:
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    f = GroundingFilter(llm_bridge=_HangingBridge(), timeout_seconds=0.05)
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 20  # raw passed through
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is False
    assert trace["degraded_reason"] == "llm_timeout"


@pytest.mark.asyncio
async def test_llm_exception_degrades_to_raw() -> None:
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    f = GroundingFilter(
        llm_bridge=_RaisingBridge(RuntimeError("LLM exploded")),
        timeout_seconds=1.0,
    )
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 20
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is False
    assert "llm_exception" in trace["degraded_reason"]


@pytest.mark.asyncio
async def test_malformed_response_degrades_to_raw() -> None:
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge("definitely not JSON")
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 20
    trace = out.trace["grounding_filter"]
    assert trace["applied"] is False
    assert trace["degraded_reason"] == "bad_response_shape"


@pytest.mark.asyncio
async def test_disabled_when_no_bridge() -> None:
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    f = GroundingFilter(llm_bridge=None, timeout_seconds=1.0)
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 20
    # No trace key written — fully disabled, never engaged.
    assert "grounding_filter" not in out.trace


@pytest.mark.asyncio
async def test_disabled_via_flag_even_with_bridge() -> None:
    events = _make_events(20)
    payload = RetrievalPayload(l1_events=events)
    bridge = _StaticBridge('{"keep": [1], "why": "x"}')
    f = GroundingFilter(llm_bridge=bridge, timeout_seconds=1.0, enabled=False)
    out = await f.apply(payload, _make_request())
    assert len(out.l1_events) == 20
    assert "grounding_filter" not in out.trace


# ---------- regression: content must reach the filter LLM in full ----------


def test_prompt_payload_includes_full_content_not_short_snippet() -> None:
    """Regression: earlier design truncated content to 80 chars and
    dropped real matches whose key passage lived past that point
    (e.g. the "猫熬我" passage was around char 200 of a real OCR
    record). Now we feed the filter LLM the full content (capped only
    by CONTENT_CAP_CHARS as a defensive net against 100KB+ rows)."""
    long_ocr = (
        "屏幕快照时间线 屏幕截图 "
        + ("EXPLORER OPEN EDITORS MAGI cache models plugins " * 5)  # UI chrome filler
        + " 黎月风 上次猫熬我，我就请假熬了它三天 摇醒 摇不醒就飞起来"
    )
    event = {
        "event_id": "ev_long",
        "source": "screenshot_timeline",
        "content": long_ocr,
        "timestamp": 1779944800,
    }
    prompt_body = _build_prompt_payload("猫叫醒人的图", [event])
    # The relevant Chinese phrase MUST appear in the payload — that's
    # the signal the filter LLM needs to keep this candidate.
    assert "猫熬我" in prompt_body
    assert "摇醒" in prompt_body
    # Content field used (not 'snippet')
    assert '"content":' in prompt_body


def test_prompt_payload_caps_pathological_content_with_marker() -> None:
    """Defensive cap: a single 100KB OCR row shouldn't single-handedly
    blow the prompt budget. Confirmed by 'truncated' marker and that
    payload size stays bounded."""
    huge = "A" * (CONTENT_CAP_CHARS + 500)
    event = {
        "event_id": "ev_huge",
        "source": "screenshot_timeline",
        "content": huge,
        "timestamp": 1779944800,
    }
    prompt_body = _build_prompt_payload("anything", [event])
    # Original is bigger than cap; payload contains the truncation marker.
    assert "[truncated]" in prompt_body
    # Even with JSON-encoded escaping, the payload comfortably stays
    # within a small multiple of the cap.
    assert len(prompt_body) < CONTENT_CAP_CHARS * 2


def test_prompt_payload_exposes_dialogue_speaker_and_query_people() -> None:
    """Dialogue retrieval needs ownership cues: 'Melanie said, I bought shoes'
    must not satisfy a query about Caroline buying shoes merely because both
    participants occur in nearby conversation text."""
    event = {
        "event_id": "ev_dialogue",
        "source": "benchmark.eval_support",
        "content": (
            "DATE: 3:40 pm on 12 June, 2023\n"
            'Melanie said, "I bought new running shoes and love them."'
        ),
        "timestamp": 1686570000,
    }

    prompt_body = _build_prompt_payload("What are Caroline's new shoes used for?", [event])

    assert '"query_named_people": ["Caroline"]' in prompt_body
    assert '"speaker": "Melanie"' in prompt_body


def test_system_prompt_requires_named_person_ownership_match() -> None:
    assert "If a query asks about a named person" in _SYSTEM_PROMPT
    assert "same named person" in _SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_filter_can_match_signal_buried_past_first_80_chars() -> None:
    """The exact failure mode that motivated dropping the 80-char cap:
    relevant keyword lives in the middle of the OCR, not the head."""
    # Fill the first ~200 chars with chrome (sidebar menu, file
    # tabs) then drop the real content at the end.
    events = _make_events(10)  # base set of 10 events (well above MIN_CANDIDATES_TO_FILTER)
    events[2] = {
        "event_id": "ev_buried",
        "source": "screenshot_timeline",
        "content": (
            "Chat\nNew session\nRoutines\nCustomize\nCowork\nCode\n"
            "Recents Fix memory tool recall Redesign task sidebar "
            "Review and evaluate Personality Review skills General coding "
            "Fix status bar layout 长长长长 chrome 占位文字一堆 ..."
            "\n\n黎月风 上次猫熬我，请假熬了它三天 摇醒 摇不醒就飞起来"
        ),
        "timestamp": 1779944803,
    }
    payload = RetrievalPayload(l1_events=events)

    # Mock bridge that 'reads' the prompt and only keeps the one with 猫.
    class _SmartBridge:
        async def chat(self, **kwargs: Any) -> str:
            user_msg = kwargs["messages"][-1]["content"]
            # Decide via substring match — what a real LLM would do.
            if "猫熬我" in user_msg:
                return '{"keep": [3], "why": "candidate 3 mentions the cat passage"}'
            return '{"keep": [], "why": "no match"}'

    f = GroundingFilter(llm_bridge=_SmartBridge(), timeout_seconds=1.0)
    out = await f.apply(payload, _make_request("猫叫醒人的图"))
    # The buried-signal candidate must survive; with old 80-char
    # snippet the "猫" passage was past the cap and got dropped.
    assert len(out.l1_events) == 1
    assert out.l1_events[0]["event_id"] == "ev_buried"


@pytest.mark.asyncio
async def test_grounding_filter_runs_on_small_candidate_set() -> None:
    """A low-recall set (3 candidates) must still be filtered — the exact
    'few hits, all noise' case. Previously skipped because len < 10."""
    bridge = _StaticBridge('{"keep": [2], "why": "only 2 (Chrome browsing) is relevant to the query"}')
    gf = GroundingFilter(llm_bridge=bridge, timeout_seconds=3.0)
    payload = RetrievalPayload(
        l1_events=[
            {"event_id": "a", "content": "杭州天气怎么样", "timestamp": 1.0},
            {"event_id": "b", "content": "Chrome 浏览 GitHub PR #42", "timestamp": 2.0},
            {"event_id": "c", "content": "我要怎么配", "timestamp": 3.0},
        ]
    )
    request = _make_request("我chrome最近在看什么")
    result = await gf.apply(payload, request)
    assert result.trace["grounding_filter"]["applied"] is True
    assert len(result.l1_events) == 1
    assert result.l1_events[0]["event_id"] == "b"
