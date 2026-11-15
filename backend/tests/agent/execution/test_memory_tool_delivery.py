"""Memory evidence must survive the production tool-message boundary."""

from copy import deepcopy
import json

import pytest

from magi.agent.execution.function_calling.postprocessor import FunctionCallingPostprocessor
from magi.agent.execution.function_calling.types import ToolCallResult


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
