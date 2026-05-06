from __future__ import annotations

import json

from magi.api.services.chat_trace.builders.rows import build_trace_row_node
from magi.api.services.chat_trace.tree import build_runtime_trace_root


def test_intent_resolution_node_includes_embedded_llm_trace_metadata() -> None:
    node = build_trace_row_node(
        span={
            "span_id": "turn-1:intent_resolution",
            "trace_id": "trace:turn-1",
            "node_type": "intent_resolution",
            "name": "Intent resolution",
            "status": "ok",
            "input_preview": "What should we do next?",
            "output_preview": "chat / direct_llm",
            "started_at_ms": 1000,
            "ended_at_ms": 1500,
            "duration_ms": 500,
        },
        llm_call=None,
        tool_call=None,
        intent_resolution={
            "intent": "chat",
            "execution_mode": "direct_llm",
            "route_reason": "small talk",
            "selected_worker_type": None,
            "selected_tools_json": json.dumps(
                {
                    "router_tools": [],
                    "selected_tools": [],
                    "task_hint": {},
                    "recommended_tools": [],
                    "llm_trace": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "input_tokens": 42,
                        "output_tokens": 9,
                        "total_tokens": 51,
                        "duration_ms": 333,
                        "thinking_enabled": False,
                        "request_preview": "What should we do next?",
                        "response_preview": "chat / direct_llm",
                    },
                }
            ),
        },
    )

    assert node.kind == "intent"
    assert node.metadata["intent_label"] == "chat"
    assert node.metadata["provider"] == "openai"
    assert node.metadata["model"] == "gpt-test"
    assert node.metadata["input_tokens"] == 42
    assert node.metadata["output_tokens"] == 9
    assert node.metadata["total_tokens"] == 51
    assert node.metadata["duration_ms"] == 333
    assert node.metadata["input"] == {"preview": "What should we do next?"}
    assert node.metadata["output"] == {"preview": "chat / direct_llm"}


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
        intent_resolution=None,
    )

    assert node.kind == "llm"
    assert node.metadata["request_preview"] == "Please summarize the trace."
    assert node.metadata["response_preview"] == "Here is the summary."
    assert node.metadata["input"] == {"preview": "Please summarize the trace."}
    assert node.metadata["output"] == {"preview": "Here is the summary."}


def test_runtime_trace_root_infers_function_calling_parent_links() -> None:
    turn_id = "turn-1"
    root = build_runtime_trace_root(
        turn={
            "turn_id": turn_id,
            "trace_id": f"trace:{turn_id}",
            "status": "completed",
            "started_at_ms": 1000,
            "ended_at_ms": 5000,
        },
        spans=[
            {
                "span_id": f"{turn_id}:turn",
                "trace_id": f"trace:{turn_id}",
                "node_type": "turn",
                "name": "Chat turn",
                "status": "completed",
                "started_at_ms": 1000,
                "ended_at_ms": 5000,
            },
            {
                "span_id": f"{turn_id}:iteration:1",
                "trace_id": f"trace:{turn_id}",
                "parent_span_id": f"{turn_id}:turn",
                "node_type": "iteration",
                "name": "Iteration 1",
                "status": "completed",
                "started_at_ms": 2000,
                "ended_at_ms": 4000,
            },
            {
                "span_id": "llm-1",
                "trace_id": f"trace:{turn_id}",
                "parent_span_id": f"{turn_id}:turn",
                "node_type": "llm_call",
                "name": "qwen",
                "status": "ok",
                "started_at_ms": 2100,
                "ended_at_ms": 2500,
            },
            {
                "span_id": "tool-call-1",
                "trace_id": f"trace:{turn_id}",
                "parent_span_id": f"{turn_id}:iteration:1",
                "node_type": "tool_call",
                "name": "web-search tool call",
                "status": "completed",
                "started_at_ms": 2500,
                "ended_at_ms": 3000,
            },
            {
                "span_id": "raw-tool-1",
                "trace_id": f"trace:{turn_id}",
                "parent_span_id": f"{turn_id}:turn",
                "node_type": "tool_invocation",
                "name": "web-search",
                "status": "ok",
                "started_at_ms": 2510,
                "ended_at_ms": 3000,
            },
        ],
        llm_calls=[],
        tool_calls=[],
        intent_resolutions=[],
    )

    iteration = next(child for child in root.children if child.kind == "iteration")
    assert [child.id for child in iteration.children] == ["llm-1", "tool-call-1"]
    assert iteration.children[1].children[0].id == "raw-tool-1"
