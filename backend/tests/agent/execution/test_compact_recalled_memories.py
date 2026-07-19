"""Tests for the message-payload projection of historical recall findings.

The chat shell renders a "called memories" row beneath each assistant bubble.
The data backing that row comes from
``FunctionCallingResponseMixin._compact_recalled_memories`` and is written
into the assistant message payload by
``_extract_assistant_message_payload_from_tool_results``. These tests pin
that projection so frontend assumptions don't drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi.agent.execution.function_calling.responses import FunctionCallingResponseMixin


class _Mixin(FunctionCallingResponseMixin):
    """Minimal concrete subclass to exercise the mixin in isolation."""


@dataclass
class _ToolCallResultStub:
    success: bool
    data: dict[str, Any]


def _make_finding(
    *,
    kind: str,
    statement: str,
    topic: str,
    layer: str = "L2",
    confidence: float | None = None,
    occurred_at: float | None = None,
    evidence_text: str | None = None,
    feedback_ref: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "statement": statement,
        "topic": topic,
        "source_layer": layer,
    }
    if confidence is not None:
        payload["confidence"] = confidence
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    if evidence_text is not None:
        payload["evidence_text"] = evidence_text
    if feedback_ref is not None:
        payload["feedback_ref"] = feedback_ref
    return payload


class TestCompactRecalledMemories:
    def test_compact_payload_carries_only_ui_fields(self):
        mixin = _Mixin()
        recalled = mixin._compact_recalled_memories(
            {
                "findings": [
                    _make_finding(
                        kind="relationship",
                        statement="self LIKES topic:hachi-mi",
                        topic="hachi-mi",
                        layer="L2",
                        confidence=0.82,
                        occurred_at=1710000000.0,
                        evidence_text="听完哈基米后说节奏太密",
                        feedback_ref="relationship:triple-1",
                    )
                ]
            }
        )
        assert recalled == [
            {
                "kind": "relationship",
                "source_layer": "L2",
                "statement": "self LIKES topic:hachi-mi",
                "topic": "hachi-mi",
                "confidence": 0.82,
                "occurred_at": 1710000000.0,
                "evidence_text": "听完哈基米后说节奏太密",
                "feedback_ref": "relationship:triple-1",
            }
        ]

    def test_compact_payload_skips_blank_statements(self):
        mixin = _Mixin()
        recalled = mixin._compact_recalled_memories(
            {
                "findings": [
                    {"kind": "event", "statement": "  ", "topic": "blank"},
                    _make_finding(kind="event", statement="Real event", topic="Real"),
                ]
            }
        )
        assert len(recalled) == 1
        assert recalled[0]["statement"] == "Real event"

    def test_compact_payload_falls_back_to_statement_when_topic_missing(self):
        mixin = _Mixin()
        recalled = mixin._compact_recalled_memories(
            {
                "findings": [
                    {
                        "kind": "event",
                        "statement": "Event without topic",
                        "source_layer": "L1",
                    }
                ]
            }
        )
        assert recalled[0]["topic"] == "Event without topic"

    def test_compact_payload_respects_limit(self):
        mixin = _Mixin()
        findings = [
            _make_finding(kind="event", statement=f"Event {i}", topic=f"E{i}") for i in range(20)
        ]
        recalled = mixin._compact_recalled_memories({"findings": findings}, limit=4)
        assert len(recalled) == 4

    def test_compact_payload_returns_empty_for_missing_findings(self):
        mixin = _Mixin()
        assert mixin._compact_recalled_memories({}) == []
        assert mixin._compact_recalled_memories({"findings": "not a list"}) == []


class TestPayloadExtractionFromToolResults:
    def test_recalled_memories_attached_when_historical_recall_present(self):
        mixin = _Mixin()
        results = [
            _ToolCallResultStub(
                success=True,
                data={
                    "historical_recall": {
                        "findings": [
                            _make_finding(
                                kind="relationship",
                                statement="self LIKES topic:hachi-mi",
                                topic="hachi-mi",
                                layer="L2",
                                confidence=0.82,
                            )
                        ]
                    }
                },
            )
        ]
        payload = mixin._extract_assistant_message_payload_from_tool_results(results)
        assert "recalled_memories" in payload
        assert payload["recalled_memories"][0]["topic"] == "hachi-mi"

    def test_structured_coverage_summary_attached_when_available(self):
        mixin = _Mixin()
        results = [
            _ToolCallResultStub(
                success=True,
                data={
                    "historical_recall": {
                        "findings": [
                            _make_finding(
                                kind="event",
                                statement="Visited example.com",
                                topic="example.com",
                                layer="L1",
                            )
                        ],
                        "coverage": {
                            "kind": "exhaustive",
                            "can_claim_total": True,
                            "total_count": 12,
                        },
                        "structured_results": [
                            {
                                "domain": "browser",
                                "summary": {"event_count": 12, "metric_total": 18},
                            }
                        ],
                    }
                },
            )
        ]

        payload = mixin._extract_assistant_message_payload_from_tool_results(results)

        assert payload["recalled_memory_summary"] == {
            "coverage_kind": "exhaustive",
            "can_claim_total": True,
            "total_count": 12,
            "domain": "browser",
        }

    def test_no_recalled_memories_when_findings_empty(self):
        mixin = _Mixin()
        results = [
            _ToolCallResultStub(
                success=True,
                data={"historical_recall": {"findings": []}},
            )
        ]
        payload = mixin._extract_assistant_message_payload_from_tool_results(results)
        assert "recalled_memories" not in payload

    def test_failed_tool_result_skipped(self):
        mixin = _Mixin()
        results = [
            _ToolCallResultStub(
                success=False,
                data={
                    "historical_recall": {
                        "findings": [
                            _make_finding(kind="event", statement="should be ignored", topic="x")
                        ]
                    }
                },
            )
        ]
        payload = mixin._extract_assistant_message_payload_from_tool_results(results)
        assert "recalled_memories" not in payload

    def test_failed_tool_result_keeps_explicit_assistant_payload(self):
        mixin = _Mixin()
        results = [
            _ToolCallResultStub(
                success=False,
                data={
                    "assistant_payload": {
                        "code_agent_delegations": [
                            {
                                "delegation_id": "delegation-1",
                                "turn_id": "turn-1",
                                "workspace_path": "/workspace",
                            }
                        ],
                    },
                    "historical_recall": {
                        "findings": [
                            _make_finding(
                                kind="event",
                                statement="should still be ignored",
                                topic="x",
                            )
                        ]
                    },
                },
            )
        ]

        payload = mixin._extract_assistant_message_payload_from_tool_results(results)

        assert payload == {
            "code_agent_delegations": [
                {
                    "delegation_id": "delegation-1",
                    "turn_id": "turn-1",
                    "workspace_path": "/workspace",
                }
            ],
        }
