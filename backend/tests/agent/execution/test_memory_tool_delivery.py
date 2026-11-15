"""Memory evidence must survive the production tool-message boundary."""

from copy import deepcopy
import json

import pytest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

from magi.agent.execution.function_calling.postprocessor import FunctionCallingPostprocessor
from magi.agent.execution.function_calling.types import ToolCallResult
from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.recall_events import govern_recall_events
from magi.memory.retrieval_projection import project_historical_recall
from magi.memory.hybrid_retrieval.timeline_condense import build_timeline_summary


def deliver(recall, *, budget=24_000):
    result = ToolCallResult(
        tool_call_id="recall-1", tool_name="memory_query", success=True,
        data={"recall": recall, "trace": {"private": "diagnostics"}},
    )
    message = FunctionCallingPostprocessor(max_payload_chars=budget).build_tool_message(
        "memory_query", result, evidence_ref="retrieval-1",
    )
    assert len(message["content"]) <= budget
    assert "diagnostics" not in message["content"]
    return json.loads(message["content"])["data"]["recall"]


@pytest.mark.parametrize("body", ["中" * 1400, '\\"\n' * 350])
def test_long_recall_keeps_whole_records_and_reports_delivery(body):
    recall = {
        "status": "found", "query_mode": "cross_session",
        "findings": [
            {"kind": "event", "statement": f"START-{i:02} {body} END-{i:02}", "author_type": "user"}
            for i in range(30)
        ],
        "coverage": {"can_claim_total": False},
    }
    original = deepcopy(recall)
    rendered = deliver(recall)
    delivery = json.loads(next(line.removeprefix("delivery: ") for line in rendered.splitlines() if line.startswith("delivery: ")))
    count = delivery["returned"]["findings"]
    assert 5 < count < 30
    assert delivery["omitted"]["findings"] == 30 - count
    assert delivery["partial"] is True
    for i in range(count):
        assert f"START-{i:02}" in rendered and f"END-{i:02}" in rendered
    assert "Assistant suggestions are not user decisions" in rendered
    assert "representative, not exhaustive" in rendered
    assert recall == original


def test_oversized_record_does_not_starve_later_short_record():
    rendered = deliver({
        "status": "found",
        "findings": [
            {"kind": "event", "statement": "too-large", "source_ref": {"identity": "x" * 8000}},
            {"kind": "event", "statement": "The later correction: do not book."},
        ],
    }, budget=2500)
    assert "too-large" not in rendered
    assert "The later correction: do not book." in rendered
    assert '"findings": 1' in rendered


def test_governance_metadata_overflow_fails_without_exposing_evidence():
    rendered = deliver({
        "status": "found", "answerability": {"reason": "x" * 5000},
        "findings": [{"kind": "event", "statement": "must not escape"}],
    }, budget=512)
    assert "delivery=unavailable" in rendered
    assert "Do not infer absence" in rendered
    assert "must not escape" not in rendered


def test_unknown_finding_kind_is_not_silently_lost():
    assert "Prior experience" in deliver({
        "status": "found", "findings": [{"kind": "experience", "statement": "Prior experience"}],
    })


@pytest.mark.asyncio
async def test_governed_neighbors_reach_chat_with_speaker_correction_and_timeline():
    memory = SimpleNamespace(l2=SimpleNamespace(
        db_path="memory.db", active_correction_evidence_event_ids=AsyncMock(return_value={"old"}),
    ))
    events = [
        {"event_id": key, "content": content, "timestamp": index + 1,
         "user_id": "owner", "session_id": "past", "source": "chat", "author_type": speaker,
         "l1_retrieval_scope": "fact_authoritative", "evidence_class": "user_self_report" if speaker == "user" else "assistant_freeform"}
        for index, (key, content, speaker) in enumerate([
            ("old", "Book on Friday.", "assistant"),
            ("hit", "Agreed, but only if the fare is refundable.", "user"),
            ("update", "Correction: do not book; the plan is cancelled.", "user"),
        ])
    ]
    request = RetrievalQuery(query="Resume the travel plan", user_id="owner")
    governed = await govern_recall_events(memory, events, request, time_range={}, historical=True)
    bundle = {"hit_event_ids": ["hit"], "answer_events": governed, "events": governed}
    payload = RetrievalPayload(
        l1_events=[events[1]], l1_evidence_bundles=[bundle],
        l1_timeline_summary=build_timeline_summary(question=request.query, evidence_bundles=[bundle]),
        trace={"query_mode": "episode_recall"},
    )
    rendered = deliver(asdict(project_historical_recall(payload=payload, request=request)))
    assert "only if the fare is refundable" in rendered
    assert "the plan is cancelled" in rendered
    assert "speaker=assistant" in rendered and "speaker=user" in rendered
    assert "later corrected" in rendered
    assert "Timeline navigation" in rendered


@pytest.mark.asyncio
async def test_expanded_evidence_obeys_scope_and_fails_closed():
    base = {"event_id": "ok", "content": "visible", "timestamp": 10, "user_id": "owner",
            "source": "chat", "l1_retrieval_scope": "fact_authoritative"}
    memory = SimpleNamespace(l2=SimpleNamespace(
        db_path="memory.db", active_correction_evidence_event_ids=AsyncMock(return_value={"corrected"}),
    ))
    events = [base, *[{**base, "event_id": name, **change} for name, change in [
        ("other-user", {"user_id": "other"}), ("other-source", {"source": "mail"}),
        ("deleted", {"deleted_at": 1}), ("runtime", {"l1_retrieval_scope": "none"}),
        ("out-of-range", {"timestamp": 30}), ("corrected", {}),
    ]]]
    request = RetrievalQuery(query="test", user_id="owner", source_filters=["chat"])
    governed = await govern_recall_events(memory, events, request, time_range={"end": 20}, historical=False)
    assert [event["event_id"] for event in governed] == ["ok"]
    memory.l2.active_correction_evidence_event_ids.side_effect = RuntimeError("unavailable")
    assert await govern_recall_events(memory, events, request, time_range={}, historical=True) == []


@pytest.mark.parametrize("limit", [1, 20, 40])
def test_requested_breadth_reaches_chat_instead_of_fixed_layer_ceiling(limit):
    payload = RetrievalPayload(l1_events=[
        {"event_id": f"e{i}", "content": f"Recorded item {i:02}", "score": 0.9}
        for i in range(50)
    ])
    recall = project_historical_recall(payload=payload, request=RetrievalQuery(
        query="List recorded items", query_mode="cross_session", limit=limit,
    ))
    assert len(recall.findings) == limit
    rendered = deliver(asdict(recall))
    assert f"Recorded item {limit - 1:02}" in rendered
    assert payload.trace["projection_budget"] == {"candidates": 50, "limit": limit, "selected": limit}
