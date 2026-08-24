from __future__ import annotations

from magi.runtime_trace.chat_trace.builders.rows import build_trace_row_node
from magi.runtime_trace.chat_trace.tree import build_runtime_trace_root


def test_llm_node_exposes_input_output_previews() -> None:
    node = build_trace_row_node(
        span={
            "span_id": "turn-1:llm_call",
            "trace_id": "trace:turn-1",
            "node_type": "llm_call",
            "name": "Main LLM call",
            "status": "ok",
            "started_at_ms": 1000,
            "ended_at_ms": 1800,
            "duration_ms": 800,
        },
        llm_call={
            "provider": "openai",
            "model": "gpt-test",
            "input_tokens": 12,
            "output_tokens": 18,
            "total_tokens": 30,
            "duration_ms": 800,
            "request_preview": "Please summarize the trace.",
            "response_preview": "Here is the summary.",
        },
        tool_call=None,
    )

    assert node.kind == "llm"
    assert node.metadata["request_preview"] == "Please summarize the trace."
    assert node.metadata["response_preview"] == "Here is the summary."
    assert node.metadata["input"] == {"preview": "Please summarize the trace."}
    assert node.metadata["output"] == {"preview": "Here is the summary."}


def _build_response_draft_trace(*, status: str):
    return build_runtime_trace_root(
        turn={
            "turn_id": "turn-1",
            "trace_id": "trace:turn-1",
            "status": status,
            "started_at_ms": 1000,
            "ended_at_ms": 2000,
            "response_preview": "uncommitted assistant draft",
        },
        spans=[
            {
                "span_id": "turn-1:turn",
                "trace_id": "trace:turn-1",
                "turn_id": "turn-1",
                "node_type": "turn",
                "name": "Chat turn",
                "status": status,
                "started_at_ms": 1000,
                "ended_at_ms": 2000,
            },
            {
                "span_id": "turn-1:llm",
                "trace_id": "trace:turn-1",
                "turn_id": "turn-1",
                "parent_span_id": "turn-1:turn",
                "node_type": "llm_call",
                "name": "Main LLM call",
                "status": "completed",
                "started_at_ms": 1100,
                "ended_at_ms": 1500,
            },
            {
                "span_id": "turn-1:iteration",
                "trace_id": "trace:turn-1",
                "turn_id": "turn-1",
                "parent_span_id": "turn-1:turn",
                "node_type": "iteration",
                "name": "Iteration 1",
                "status": "completed",
                "result_preview": "uncommitted assistant draft",
                "started_at_ms": 1500,
                "ended_at_ms": 1600,
            },
            {
                "span_id": "turn-1:tool",
                "trace_id": "trace:turn-1",
                "turn_id": "turn-1",
                "parent_span_id": "turn-1:turn",
                "node_type": "tool_call",
                "name": "Lookup",
                "status": "completed",
                "result_preview": "tool evidence",
                "started_at_ms": 1200,
                "ended_at_ms": 1300,
            },
            {
                "span_id": "turn-1:response_emit",
                "trace_id": "trace:turn-1",
                "turn_id": "turn-1",
                "parent_span_id": "turn-1:turn",
                "node_type": "response_emit",
                "name": "Response emission",
                "status": "completed",
                "result_preview": "uncommitted assistant draft",
                "started_at_ms": 1700,
                "ended_at_ms": 1700,
            },
            {
                "span_id": "turn-1:rhythm",
                "trace_id": "trace:turn-1",
                "turn_id": "turn-1",
                "parent_span_id": "turn-1:turn",
                "node_type": "rhythm_processing",
                "name": "Response rhythm",
                "status": "completed",
                "result_preview": "2 message segments",
                "started_at_ms": 1650,
                "ended_at_ms": 1690,
            },
        ],
        llm_calls=[
            {
                "span_id": "turn-1:llm",
                "provider": "openai",
                "model": "gpt-test",
                "request_preview": "user request",
                "response_preview": "uncommitted assistant draft",
                "thinking_content": "private draft reasoning",
            }
        ],
        tool_calls=[
            {
                "span_id": "turn-1:tool",
                "tool_name": "lookup",
                "result_preview": "tool evidence",
            }
        ],
    )


def test_cancelled_trace_hides_uncommitted_drafts_but_keeps_tool_evidence() -> None:
    root = _build_response_draft_trace(status="cancelled")
    children = {node.kind: node for node in root.children}

    assert root.result_preview == ""
    assert "response" not in children
    assert "rhythm" not in children
    assert children["llm"].result_preview == ""
    assert children["iteration"].result_preview == ""
    assert "response_preview" not in children["llm"].metadata
    assert "thinking_content" not in children["llm"].metadata
    assert "output" not in children["llm"].metadata
    assert children["tool"].result_preview == "tool evidence"


def test_completed_trace_keeps_committed_response_previews() -> None:
    root = _build_response_draft_trace(status="completed")
    children = {node.kind: node for node in root.children}

    assert root.result_preview == "uncommitted assistant draft"
    assert children["llm"].result_preview == "uncommitted assistant draft"
    assert children["iteration"].result_preview == "uncommitted assistant draft"
    assert children["response"].result_preview == "uncommitted assistant draft"
    assert children["rhythm"].result_preview == "2 message segments"
    assert children["tool"].result_preview == "tool evidence"
