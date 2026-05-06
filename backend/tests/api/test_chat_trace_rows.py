from __future__ import annotations

import json

from magi.api.services.chat_trace.builders.rows import build_trace_row_node


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
