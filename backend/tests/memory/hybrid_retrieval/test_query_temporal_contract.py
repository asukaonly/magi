"""Scripted semantic judgments exercise host policy, not model accuracy."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from magi.memory.hybrid_retrieval import combined_intent_decider
from magi.memory.hybrid_retrieval.combined_intent_decider import IntentDecider
from magi.memory.hybrid_retrieval.llm_intent import LLMIntentDecider, _LLM_SYSTEM_PROMPT
from magi.memory.hybrid_retrieval.mode_registry import MODE_REGISTRY
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
    TimeRange,
)
from magi.memory.hybrid_retrieval.query_temporal import (
    QueryTemporalJudgment,
    resolve_query_temporal,
)
from magi.memory.hybrid_retrieval.rule_intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.service import HybridRetrievalService

ZONE = "Asia/Shanghai"
ANCHOR = datetime(2026, 9, 23, 15, 0, tzinfo=ZoneInfo(ZONE)).timestamp()


def _calendar(raw, expression):
    return {"kind": "calendar", "mode": "during", "raw_expression": raw, "expression": expression}


def _decider(response, **kwargs):
    bridge = SimpleNamespace(chat=AsyncMock(return_value=json.dumps(response)))
    decider = IntentDecider(
        rule_engine=RuleBasedIntentDecider(), llm_decider=LLMIntentDecider(bridge), **kwargs
    )
    return decider, bridge


@pytest.fixture(autouse=True)
def frozen_query_context(monkeypatch):
    monkeypatch.setattr(combined_intent_decider.time, "time", lambda: ANCHOR)
    monkeypatch.setattr(combined_intent_decider, "local_calendar_timezone_id", lambda: ZONE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expression", "start", "end"),
    [
        (
            "昨天",
            {"kind": "relative_period", "unit": "day", "offset": -1},
            "2026-09-22",
            "2026-09-23",
        ),
        (
            "前天",
            {"kind": "relative_period", "unit": "day", "offset": -2},
            "2026-09-21",
            "2026-09-22",
        ),
        (
            "the day before yesterday",
            {"kind": "relative_period", "unit": "day", "offset": -2},
            "2026-09-21",
            "2026-09-22",
        ),
        (
            "这周",
            {"kind": "relative_period", "unit": "week", "offset": 0},
            "2026-09-21",
            "2026-09-28",
        ),
        (
            "last week",
            {"kind": "relative_period", "unit": "week", "offset": -1},
            "2026-09-14",
            "2026-09-21",
        ),
        ("下周一", {"kind": "weekday", "week_offset": 1, "weekday": 0}, "2026-09-28", "2026-09-29"),
        (
            "下星期一",
            {"kind": "weekday", "week_offset": 1, "weekday": 0},
            "2026-09-28",
            "2026-09-29",
        ),
        (
            "下月",
            {"kind": "relative_period", "unit": "month", "offset": 1},
            "2026-10-01",
            "2026-11-01",
        ),
        (
            "下个月",
            {"kind": "relative_period", "unit": "month", "offset": 1},
            "2026-10-01",
            "2026-11-01",
        ),
        (
            "去年",
            {"kind": "relative_period", "unit": "year", "offset": -1},
            "2025-01-01",
            "2026-01-01",
        ),
        (
            "2024年12月28日",
            {"kind": "absolute", "unit": "day", "year": 2024, "month": 12, "day": 28},
            "2024-12-28",
            "2024-12-29",
        ),
        (
            "December 2024",
            {"kind": "absolute", "unit": "month", "year": 2024, "month": 12},
            "2024-12-01",
            "2025-01-01",
        ),
        ("2024年", {"kind": "absolute", "unit": "year", "year": 2024}, "2024-01-01", "2025-01-01"),
        (
            "今年上半年",
            {"kind": "month_window", "year_offset": 0, "start_month": 1, "month_count": 6},
            "2026-01-01",
            "2026-07-01",
        ),
    ],
)
async def test_typed_calendar_semantics_reach_every_plan(raw, expression, start, end):
    query = f"查一下 {raw} 的记录"
    decider, bridge = _decider({"query_temporal": _calendar(raw, expression)})
    result = await decider.decide(IntentDeciderInput(query=query))
    expected_start = datetime.fromisoformat(start).replace(tzinfo=ZoneInfo(ZONE)).timestamp()
    exclusive_end = datetime.fromisoformat(end).replace(tzinfo=ZoneInfo(ZONE)).timestamp()
    assert result.time_range == TimeRange(
        start=expected_start, end=math.nextafter(exclusive_end, -math.inf)
    )
    assert all(plan.time_range == result.time_range for plan in result.plans)
    assert bridge.chat.await_count == 1
    assert bridge.chat.call_args.kwargs["messages"] == [
        {"role": "user", "content": f"user query: {query}"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "不要只看最近7天，查所有长期偏好",
        "并非只查询昨天，查全部记录",
        "请查《去年》的阅读记录",
        "Find my notes about 'last week', without a time restriction",
        "我当前有哪些长期偏好？",
    ],
)
@pytest.mark.parametrize("judgment", [None, {"kind": "none"}])
async def test_semantic_none_or_unknown_never_reapplies_time_keywords(query, judgment):
    decider, _ = _decider({"query_mode": "current_state", "query_temporal": judgment})
    result = await decider.decide(IntentDeciderInput(query=query))
    assert result.time_range is None
    assert all(plan.time_range is None for plan in result.plans)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["no_model", "timeout", "invalid_json"])
async def test_semantic_failure_does_not_create_a_time_filter(failure):
    decider, bridge = _decider({})
    if failure == "no_model":
        decider = IntentDecider(rule_engine=RuleBasedIntentDecider())
    elif failure == "timeout":
        bridge.chat.side_effect = TimeoutError("synthetic timeout")
    else:
        bridge.chat.return_value = "not json"
    result = await decider.decide(IntentDeciderInput(query="不要限制最近7天，查询2024年的所有偏好"))
    assert result.time_range is None
    assert result.source == "rule_fallback"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_range", [{"start": 100, "end": 200}, {"as_of": 123}, {"relative": "7d"}]
)
@pytest.mark.parametrize(
    "judgment",
    [{"kind": "none"}, _calendar("昨天", {"kind": "relative_period", "unit": "day", "offset": -1})],
)
async def test_explicit_caller_range_always_wins(raw_range, judgment):
    inp = IntentDeciderInput(query="昨天有什么记录", raw_time_range=raw_range)
    expected = RuleBasedIntentDecider().evaluate(inp).time_range
    decider, _ = _decider({"query_temporal": judgment})
    result = await decider.decide(inp)
    assert result.time_range == expected
    assert all(plan.time_range == expected for plan in result.plans)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_range", [{}, {"relative": "invalid"}, {"relative": "7days"}, {"invented": 1}]
)
async def test_unrecognized_caller_range_never_falls_back_to_query_or_model(raw_range):
    decider, _ = _decider(
        {
            "query_temporal": _calendar(
                "昨天", {"kind": "relative_period", "unit": "day", "offset": -1}
            )
        }
    )
    result = await decider.decide(IntentDeciderInput(query="昨天的记录", raw_time_range=raw_range))
    assert result.time_range is None


@pytest.mark.asyncio
async def test_invalid_explicit_boundary_reports_error_without_inventing_range():
    decider, bridge = _decider({"query_temporal": {"kind": "none"}})
    with pytest.raises(ValueError):
        await decider.decide(IntentDeciderInput(query="昨天的记录", raw_time_range={"start": True}))
    assert bridge.chat.await_count == 0


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"kind": "none", "start": 0},
        {"kind": "calendar", "raw_expression": "昨天"},
        _calendar("", {"kind": "relative_period", "unit": "day", "offset": -1}),
        _calendar("昨天", {"kind": "relative_period", "unit": "day", "offset": True}),
        _calendar("昨天", {"kind": "relative_period", "unit": "day", "offset": -1, "anchor": 0}),
        _calendar("现在", {"kind": "at_observation"}),
    ],
)
def test_invalid_judgments_do_not_cross_the_type_boundary(value):
    assert QueryTemporalJudgment.from_dict(value) is None


@pytest.mark.parametrize(
    ("query", "timezone_id"),
    [("前天的记录", ZONE), ("昨天的记录", None), ("昨天的记录", "invalid/zone")],
)
def test_invalid_evidence_or_host_zone_keeps_query_unbounded(query, timezone_id):
    judgment = QueryTemporalJudgment.from_dict(
        _calendar("昨天", {"kind": "relative_period", "unit": "day", "offset": -1})
    )
    assert (
        resolve_query_temporal(
            judgment, query=query, anchor_timestamp=ANCHOR, timezone_id=timezone_id
        )
        is None
    )


def test_calendar_range_uses_host_timezone_across_dst():
    judgment = QueryTemporalJudgment.from_dict(
        _calendar(
            "2026-03-08", {"kind": "absolute", "unit": "day", "year": 2026, "month": 3, "day": 8}
        )
    )
    result = resolve_query_temporal(
        judgment,
        query="2026-03-08 records",
        anchor_timestamp=ANCHOR,
        timezone_id="America/New_York",
    )
    assert result.end - result.start == pytest.approx(23 * 3600, abs=1e-6)


@pytest.mark.asyncio
async def test_anchor_is_frozen_before_model_latency(monkeypatch):
    decider, bridge = _decider({})

    async def response(**kwargs):
        monkeypatch.setattr(combined_intent_decider.time, "time", lambda: ANCHOR + 86400)
        monkeypatch.setattr(
            combined_intent_decider, "local_calendar_timezone_id", lambda: "America/New_York"
        )
        return json.dumps(
            {
                "query_temporal": _calendar(
                    "今天", {"kind": "relative_period", "unit": "day", "offset": 0}
                )
            }
        )

    bridge.chat.side_effect = response
    result = await decider.decide(IntentDeciderInput(query="今天的记录"))
    assert result.time_range.start == datetime(2026, 9, 23, tzinfo=ZoneInfo(ZONE)).timestamp()


@pytest.mark.parametrize("mode", sorted(MODE_REGISTRY))
@pytest.mark.asyncio
async def test_all_supported_modes_preserve_explicit_caller_choice(mode):
    decider, _ = _decider({"query_mode": "summary" if mode != "summary" else "exact_fact"})
    result = await decider.decide(IntentDeciderInput(query="查记录", query_mode_hint=mode))
    assert result.query_mode == mode
    assert f"{mode} (" in " ".join(_LLM_SYSTEM_PROMPT.split())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"query_mode": "summary"},
        {"recall_shape": {"domain_hint": "photo", "operation": "count"}},
        {"query_temporal": {"kind": "none"}},
        {"evidence_focus": "declared"},
    ],
)
async def test_valid_typed_only_output_is_not_discarded(fields):
    decider, _ = _decider(fields)
    result = await decider.decide(IntentDeciderInput(query="查记录"))
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_applied_mode_shape_and_time_are_visible_in_shadow_diff():
    callback = AsyncMock()
    decider, _ = _decider(
        {
            "query_mode": "summary",
            "recall_shape": {"domain_hint": "photo", "operation": "count"},
            "query_temporal": _calendar(
                "昨天", {"kind": "relative_period", "unit": "day", "offset": -1}
            ),
        },
        eval_callback=callback,
    )
    await decider.decide(IntentDeciderInput(query="昨天有多少照片"))
    await asyncio.gather(*decider._background_tasks)
    record = callback.call_args.args[0]
    assert record.diff_summary == "applied: query_mode,recall_shape,time_range"


@pytest.mark.asyncio
async def test_overridden_model_mode_and_time_are_not_logged_as_applied():
    callback = AsyncMock()
    decider, _ = _decider(
        {"query_mode": "summary", "query_temporal": {"kind": "none"}}, eval_callback=callback
    )
    await decider.decide(
        IntentDeciderInput(
            query="查记录", query_mode_hint="exact_fact", raw_time_range={"as_of": 123}
        )
    )
    await asyncio.gather(*decider._background_tasks)
    assert callback.call_args.args[0].diff_summary == "applied: empty"


@pytest.mark.asyncio
async def test_service_augmentation_and_rule_backstop_share_semantic_range():
    decider, _ = _decider(
        {
            "query_mode": "summary",
            "query_temporal": _calendar(
                "昨天", {"kind": "relative_period", "unit": "day", "offset": -1}
            ),
        }
    )
    inp = IntentDeciderInput(query="昨天的记录")
    decision = await decider.decide(inp)
    memory = SimpleNamespace(l0=None, l1=None, l2=None, l2_entity_catalog=None, l3=None, l4=None)
    service = HybridRetrievalService(
        memory, config=RetrievalConfig(intent_decider_llm_enabled=False)
    )
    service._intent_decider = decider
    request = RetrievalQuery(query=inp.query)
    payload = RetrievalPayload()
    primary = service._prepare_primary_plans(decision, request=request, payload=payload)
    assert all(plan.time_range == decision.time_range for plan in primary)
    service._rule_backstop_reason = lambda **kwargs: "synthetic backstop"
    service._comparison_backstop_queries = lambda **kwargs: []
    service._execute_and_merge_plans = AsyncMock()
    await service._run_backstops(request, decision, inp, payload, l1=None, primary_plans=[])
    backstop = service._execute_and_merge_plans.call_args.args[0]
    assert backstop
    assert all(plan.time_range == decision.time_range for plan in backstop)


@pytest.mark.asyncio
async def test_service_does_not_reinject_temporal_plan_for_rejected_time_phrase():
    decider, _ = _decider({"query_mode": "event_stream", "query_temporal": {"kind": "none"}})
    memory = SimpleNamespace(l0=None, l1=None, l2=None, l2_entity_catalog=None, l3=None, l4=None)
    service = HybridRetrievalService(
        memory, config=RetrievalConfig(intent_decider_llm_enabled=False)
    )
    service._intent_decider = decider
    payload = await service.query(RetrievalQuery(query="不要限制最近7天，查全部记录"))
    assert not payload.trace.get("l2_temporal_injected")
    assert payload.trace["resolved_query_mode"] == "event_stream"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("unit", "seconds"), [("minute", 60), ("hour", 3600), ("day", 86400), ("week", 604800)]
)
@pytest.mark.parametrize("count", [1, 2, 7, 30])
async def test_rolling_window_covers_every_requested_unit(unit, seconds, count):
    raw = f"past {count} {unit}s"
    decider, _ = _decider(
        {
            "query_temporal": {
                "kind": "rolling_window",
                "raw_expression": raw,
                "unit": unit,
                "count": count,
            }
        }
    )
    result = await decider.decide(IntentDeciderInput(query=f"Find records in the {raw}"))
    assert result.time_range == TimeRange(start=ANCHOR - count * seconds, end=ANCHOR)
    assert all(plan.time_range == result.time_range for plan in result.plans)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "mode", "boundary", "expected"),
    [
        (
            "去年之前的记录",
            "before",
            "start",
            TimeRange(
                end=math.nextafter(
                    datetime(2025, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp(), -math.inf
                )
            ),
        ),
        (
            "截至去年年底的记录",
            "before",
            "end",
            TimeRange(
                end=math.nextafter(
                    datetime(2026, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp(), -math.inf
                )
            ),
        ),
        (
            "去年之后的记录",
            "after",
            "end",
            TimeRange(start=datetime(2026, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp()),
        ),
        (
            "从去年年初起的记录",
            "since",
            "start",
            TimeRange(start=datetime(2025, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp()),
        ),
        (
            "去年年初之后的记录",
            "after",
            "start",
            TimeRange(
                start=math.nextafter(
                    datetime(2025, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp(), math.inf
                )
            ),
        ),
        (
            "去年年底时的偏好",
            "as_of",
            "end",
            TimeRange(
                as_of=math.nextafter(
                    datetime(2026, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp(), -math.inf
                )
            ),
        ),
        (
            "去年年初时的偏好",
            "as_of",
            "start",
            TimeRange(as_of=datetime(2025, 1, 1, tzinfo=ZoneInfo(ZONE)).timestamp()),
        ),
    ],
)
async def test_calendar_relation_requires_explicit_semantic_boundary(
    query, mode, boundary, expected
):
    decider, _ = _decider(
        {
            "query_temporal": {
                "kind": "calendar",
                "mode": mode,
                "boundary": boundary,
                "raw_expression": query[:-3],
                "expression": {"kind": "relative_period", "unit": "year", "offset": -1},
            }
        }
    )
    result = await decider.decide(IntentDeciderInput(query=query))
    assert result.time_range == expected
    assert all(plan.time_range == expected for plan in result.plans)


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "rolling_window", "raw_expression": "recently", "unit": "day", "count": 0},
        {"kind": "rolling_window", "raw_expression": "recently", "unit": "day", "count": True},
        {"kind": "rolling_window", "raw_expression": "recently", "unit": "day", "count": 2.5},
        {"kind": "rolling_window", "raw_expression": "recently", "unit": "day", "count": 10001},
        {"kind": "rolling_window", "raw_expression": "recently", "unit": "month", "count": 1},
        {
            "kind": "rolling_window",
            "raw_expression": "recently",
            "unit": "day",
            "count": 7,
            "anchor": 0,
        },
        {
            "kind": "calendar",
            "mode": "before",
            "raw_expression": "去年之前",
            "expression": {"kind": "relative_period", "unit": "year", "offset": -1},
        },
        {
            "kind": "calendar",
            "mode": "during",
            "boundary": "end",
            "raw_expression": "去年",
            "expression": {"kind": "relative_period", "unit": "year", "offset": -1},
        },
        {
            "kind": "calendar",
            "mode": "current",
            "raw_expression": "去年",
            "expression": {"kind": "relative_period", "unit": "year", "offset": -1},
        },
    ],
)
def test_rolling_and_calendar_modes_reject_ambiguous_or_forged_operands(value):
    assert QueryTemporalJudgment.from_dict(value) is None


@pytest.mark.parametrize(
    "raw_range",
    [
        {"start": float("nan")},
        {"end": float("inf")},
        {"as_of": "-inf"},
        {"start": 2, "end": 1},
        {"as_of": 1, "start": 0},
        {"as_of": 1, "relative": "7d"},
        {"start": 1, "relative": "7d"},
        {"relative": "0d"},
        {"relative": "10001w"},
    ],
)
def test_explicit_caller_boundary_rejects_nonfinite_conflicting_or_reversed_values(raw_range):
    with pytest.raises(ValueError):
        RuleBasedIntentDecider().evaluate(
            IntentDeciderInput(query="最近7天的记录", raw_time_range=raw_range)
        )
