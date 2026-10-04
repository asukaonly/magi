"""Unified grounding contracts: exact evidence selection and safe degradation."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.grounding_filter import GroundingFilter
from magi.memory.hybrid_retrieval.grounding_filter_prompt import (
    CONTENT_CAP_CHARS,
    build_prompt_payload,
)
from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery


def _payload(event_count=3, relationship_count=3):
    return RetrievalPayload(
        l1_events=[
            {
                "event_id": f"event-{i}",
                "source": "screenshot_timeline",
                "content": f"Distinct OCR record {i}",
                "timestamp": 1779944800 + i,
            }
            for i in range(event_count)
        ],
        l2_relationships=[
            {
                "subject_id": f"person-{i}",
                "object_id": f"boss-{i}",
                "predicate": "REPORTS_TO",
                "natural_summary": f"同事 {i} 向老板 {i} 汇报",
                "confidence": 0.8,
            }
            for i in range(relationship_count)
        ],
        l3_reflections=[{"id": "unrelated-summary", "content": "Preserve this layer"}],
        trace={"retrieval": {"channel": "original"}},
    )


def _request(query="我同事的老板是谁"):
    return RetrievalQuery(query=query, user_id="local_user")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events,rels,keep,event_rows,rel_rows",
    [
        pytest.param(3, 0, [1, 3], [0, 2], [], id="events"),
        pytest.param(0, 3, [1, 3], [], [0, 2], id="relationships"),
        pytest.param(3, 4, [2, 5], [1], [1], id="unified-index-offset"),
        pytest.param(1, 1, [2], [], [0], id="two-combined-candidates"),
        pytest.param(3, 3, [2, 2, 1, 5, 5], [1, 0], [1], id="deduplicate-indices"),
        pytest.param(3, 0, [], [], [], id="empty-event-verdict"),
        pytest.param(0, 3, [], [], [], id="empty-relationship-verdict"),
        pytest.param(3, 3, [], [], [], id="empty-mixed-verdict"),
    ],
)
async def test_one_verdict_selects_exact_evidence(events, rels, keep, event_rows, rel_rows):
    payload = _payload(events, rels)
    before = deepcopy(payload)
    bridge = SimpleNamespace(
        chat=AsyncMock(return_value=json.dumps({"keep": keep, "why": "relevant"}))
    )
    out = await GroundingFilter(llm_bridge=bridge).apply(payload, _request())
    assert out is payload
    assert out.l1_events == [before.l1_events[i] for i in event_rows]
    assert out.l2_relationships == [before.l2_relationships[i] for i in rel_rows]
    assert out.l3_reflections == before.l3_reflections
    assert out.trace["retrieval"] == before.trace["retrieval"]
    bridge.chat.assert_awaited_once()
    prompt = json.loads(bridge.chat.await_args.kwargs["messages"][0]["content"])
    assert prompt["query"] == _request().query
    assert [c["idx"] for c in prompt["candidates"]] == list(range(1, events + rels + 1))
    assert [c["type"] for c in prompt["candidates"]] == ["event"] * events + ["relationship"] * rels
    assert [c["content"] for c in prompt["candidates"][:events]] == [
        e["content"] for e in before.l1_events
    ]
    assert [c["statement"] for c in prompt["candidates"][events:]] == [
        r["natural_summary"] for r in before.l2_relationships
    ]
    trace = out.trace["grounding_filter"]
    assert {
        k: trace[k]
        for k in (
            "applied",
            "input_count",
            "input_events",
            "input_relationships",
            "kept_events",
            "kept_relationships",
            "kept_count",
            "why",
        )
    } == {
        "applied": True,
        "input_count": events + rels,
        "input_events": events,
        "input_relationships": rels,
        "kept_events": len(event_rows),
        "kept_relationships": len(rel_rows),
        "kept_count": len(event_rows) + len(rel_rows),
        "why": "relevant",
    }
    assert out.trace["grounding_filter_l2"]["input_count"] == rels
    assert out.trace["grounding_filter_l2"]["kept_count"] == len(rel_rows)
    if not keep:
        assert trace["all_dropped"] is True
        assert out.trace["grounding_filter_l2"]["all_dropped"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,reason",
    [
        pytest.param("not JSON", "bad_response_shape", id="malformed-json"),
        pytest.param('{"no_keep_field":true}', "bad_response_shape", id="missing-key"),
        pytest.param("", "bad_response_shape", id="empty-response"),
        pytest.param('{"keep":["1","4"]}', "bad_response_shape", id="string-indices"),
        pytest.param('{"keep":[true,false,2]}', "bad_response_shape", id="boolean-indices"),
        pytest.param('{"keep":[1.5]}', "bad_response_shape", id="float-index"),
        pytest.param('{"keep":[{}]}', "bad_response_shape", id="object-index"),
        pytest.param('{"keep":[1,"bad"]}', "bad_response_shape", id="partly-valid-types"),
        pytest.param('{"keep":[1,999,2]}', "no_valid_indices", id="partly-valid-range"),
        pytest.param('{"keep":[999]}', "no_valid_indices", id="all-out-of-range"),
        pytest.param('{"keep":[0]}', "no_valid_indices", id="zero-index"),
        pytest.param(RuntimeError("LLM failed"), "llm_exception:RuntimeError", id="provider-error"),
        pytest.param("hang", "llm_timeout", id="timeout"),
    ],
)
async def test_failed_verdict_preserves_complete_ordered_payload(response, reason):
    # Include evidence beyond the 60-per-type model window to catch tail loss.
    payload = _payload(61, 62)
    before = deepcopy(payload)
    cancelled = asyncio.Event()

    async def hang(**_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    chat = AsyncMock(return_value=response)
    if isinstance(response, Exception):
        chat.side_effect = response
    elif response == "hang":
        chat.side_effect = hang
    out = await GroundingFilter(llm_bridge=SimpleNamespace(chat=chat), timeout_seconds=0.01).apply(
        payload, _request()
    )
    assert out is payload
    assert out.l1_events == before.l1_events
    assert out.l2_relationships == before.l2_relationships
    assert out.l3_reflections == before.l3_reflections
    assert out.trace["retrieval"] == before.trace["retrieval"]
    assert out.trace["grounding_filter"]["applied"] is False
    assert out.trace["grounding_filter"]["degraded_reason"] == reason
    assert out.trace["grounding_filter_l2"]["applied"] is False
    chat.assert_awaited_once()
    if response == "hang":
        assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("events,rels", [(3, 0), (0, 3), (3, 3)])
@pytest.mark.parametrize("mode", ["no-bridge", "disabled"])
async def test_disabled_filter_preserves_payload_without_model_call(events, rels, mode):
    payload = _payload(events, rels)
    before = deepcopy(payload)
    chat = AsyncMock(return_value='{"keep":[]}')
    bridge = None if mode == "no-bridge" else SimpleNamespace(chat=chat)
    out = await GroundingFilter(llm_bridge=bridge, enabled=mode != "disabled").apply(
        payload, _request()
    )
    assert out == before
    chat.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events,rels,query,reason",
    [
        (0, 0, "query", "trivial_count"),
        (1, 0, "query", "trivial_count"),
        (0, 1, "query", "trivial_count"),
        (2, 2, "  ", "empty_query"),
    ],
)
async def test_unjudgeable_payload_skips_model(events, rels, query, reason):
    payload = _payload(events, rels)
    before = deepcopy(payload)
    chat = AsyncMock(return_value='{"keep":[]}')
    out = await GroundingFilter(llm_bridge=SimpleNamespace(chat=chat)).apply(
        payload, _request(query)
    )
    assert out.l1_events == before.l1_events
    assert out.l2_relationships == before.l2_relationships
    assert out.l3_reflections == before.l3_reflections
    assert out.trace["grounding_filter"] == {
        "applied": False,
        "skipped_reason": reason,
        "input_count": events + rels,
    }
    assert out.trace["grounding_filter_l2"] == out.trace["grounding_filter"]
    chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_prose_wrapped_verdict_is_applied():
    payload = _payload(3, 0)
    expected = deepcopy(payload.l1_events[1])
    chat = AsyncMock(return_value='Sure! Here is the result:\n{"keep":[2],"why":"matched"}\nDone.')
    out = await GroundingFilter(llm_bridge=SimpleNamespace(chat=chat)).apply(payload, _request())
    assert out.l1_events == [expected]
    assert out.trace["grounding_filter"]["why"] == "matched"
    chat.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Summarize my music preferences",
        "List my preferences",
        "Tell me about Jazz",
        "What are Caroline's new shoes used for?",
    ],
)
async def test_unresolved_names_never_remove_candidates_before_model(query):
    payload = _payload(2, 1)
    payload.l1_events[0]["content"] = 'Melanie said, "I bought shoes."'
    payload.l2_relationships[0].update(subject_name="Asuka", natural_summary="Asuka likes jazz")
    before = deepcopy(payload)
    chat = AsyncMock(return_value='{"keep":[1,2,3]}')
    out = await GroundingFilter(llm_bridge=SimpleNamespace(chat=chat)).apply(
        payload, _request(query)
    )
    assert out.l1_events == before.l1_events
    assert out.l2_relationships == before.l2_relationships
    chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_ocr_reaches_model_and_drives_evidence_selection():
    payload = _payload(3, 0)
    payload.l1_events[2]["content"] = (
        "EXPLORER OPEN EDITORS MAGI " * 10 + "上次猫熬我，请假熬了它三天 摇醒"
    )
    expected = deepcopy(payload.l1_events[2])

    def select(**kwargs):
        prompt = json.loads(kwargs["messages"][0]["content"])
        assert prompt["candidates"][2]["content"] == expected["content"]
        return json.dumps(
            {"keep": [c["idx"] for c in prompt["candidates"] if "猫熬我" in c["content"]]}
        )

    chat = AsyncMock(side_effect=select)
    out = await GroundingFilter(llm_bridge=SimpleNamespace(chat=chat)).apply(
        payload, _request("猫叫醒人的图")
    )
    assert out.l1_events == [expected]
    chat.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "relationship"])
@pytest.mark.parametrize("excess", [-1, 0, 500])
async def test_model_content_cap_preserves_exact_prefix(kind, excess):
    payload = _payload(1, 1)
    content = ("0123456789猫" * 500)[: CONTENT_CAP_CHARS + excess]
    field = "content" if kind == "event" else "natural_summary"
    record = payload.l1_events[0] if kind == "event" else payload.l2_relationships[0]
    record[field] = content
    before = deepcopy(payload)
    chat = AsyncMock(return_value='{"keep":[1,2]}')
    out = await GroundingFilter(llm_bridge=SimpleNamespace(chat=chat)).apply(payload, _request())
    prompt = json.loads(chat.await_args.kwargs["messages"][0]["content"])
    candidate = prompt["candidates"][0 if kind == "event" else 1]
    expected = content if excess <= 0 else content[:CONTENT_CAP_CHARS] + "…[truncated]"
    assert candidate["content" if kind == "event" else "statement"] == expected
    assert out.l1_events == before.l1_events
    assert out.l2_relationships == before.l2_relationships


def test_dialogue_prompt_identifies_speaker_without_inventing_query_people():
    event = {
        "content": 'DATE: 3:40 pm on 12 June, 2023\nMelanie said, "I bought new running shoes."'
    }
    body = json.loads(build_prompt_payload("What are Caroline's new shoes used for?", [event]))
    assert "query_named_people" not in body
    assert body["candidates"][0]["speaker"] == "Melanie"
