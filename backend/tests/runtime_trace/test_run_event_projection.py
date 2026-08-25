from __future__ import annotations

import json
import sqlite3

from _shared.db_schema import apply_chain_schema

from magi.runtime_trace.run_events import AgentRunEvent, AgentRunEventType
from magi.runtime_trace.chat_trace.detail_enrichment import enrich_projected_trace
from magi.runtime_trace.chat_trace.read_service import ChatTraceReadService
from magi.runtime_trace.chat_trace.run_event_projection import project_run_events


def _event(
    sequence: int,
    event_type: AgentRunEventType,
    *,
    step_index: int | None = None,
    payload: dict | None = None,
) -> AgentRunEvent:
    return AgentRunEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        sequence=sequence,
        event_type=event_type,
        created_at_ms=1_000 + sequence * 100,
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        step_index=step_index,
        payload=dict(payload or {}),
    )


def test_projection_builds_plan_worker_validation_repair_and_metrics() -> None:
    events = [
        _event(1, AgentRunEventType.RUN_STARTED),
        _event(2, AgentRunEventType.STEP_STARTED, step_index=1),
        _event(
            3,
            AgentRunEventType.MODEL_OUTPUT,
            step_index=1,
            payload={
                "llm_trace": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "reasoning_tokens": 2,
                }
            },
        ),
        _event(
            4,
            AgentRunEventType.TOOL_CALL_REQUESTED,
            step_index=1,
            payload={"tool_calls": [{"id": "call-1", "name": "todo_write"}]},
        ),
        _event(
            5,
            AgentRunEventType.TOOL_RESULT,
            step_index=1,
            payload={
                "source": "todo_write",
                "status": "succeeded",
                "metadata": {"tool_call_id": "call-1"},
            },
        ),
        _event(6, AgentRunEventType.PLAN_UPDATED, step_index=1),
        _event(
            7,
            AgentRunEventType.CHILD_STARTED,
            step_index=1,
            payload={"child_run_id": "child-1", "preset": "review"},
        ),
        _event(
            8,
            AgentRunEventType.CHILD_COMPLETED,
            step_index=1,
            payload={"child_run_id": "child-1", "preset": "review", "status": "completed"},
        ),
        _event(
            9,
            AgentRunEventType.VALIDATION_COMPLETED,
            step_index=1,
            payload={"success": False},
        ),
        _event(
            10,
            AgentRunEventType.COMPLETION_REJECTED,
            step_index=1,
            payload={"reason_code": "validation_failed", "repairable": True},
        ),
        _event(
            11,
            AgentRunEventType.REASONING_DEPTH_CHANGED,
            step_index=1,
            payload={"previous_depth": "low", "effective_depth": "medium"},
        ),
        _event(
            12,
            AgentRunEventType.REPAIR_STARTED,
            step_index=1,
            payload={"repair_iteration": 1, "reason_code": "validation_failed"},
        ),
        _event(13, AgentRunEventType.RUN_COMPLETED, step_index=2),
    ]

    snapshot = project_run_events(
        events,
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        run_plan={
            "items": [
                {"id": "todo-1", "content": "Inspect", "status": "completed"},
                {"id": "todo-2", "content": "Fix", "status": "in_progress"},
            ]
        },
    )

    assert snapshot is not None
    assert snapshot.status == "completed"
    assert snapshot.summary.plan_summary is not None
    assert [step.label for step in snapshot.summary.plan_summary.steps] == ["Inspect", "Fix"]
    assert snapshot.summary.plan_summary.remaining_steps == 1
    assert snapshot.summary.runtime_metrics == {
        "runtime_latency_ms": 1200,
        "first_action_latency_ms": 200,
        "model_calls": 1,
        "tool_calls": 1,
        "tool_failures": 0,
        "tool_recovery_expansions": 0,
        "validation_attempts": 1,
        "validation_failures": 1,
        "repair_iterations": 1,
        "repair_exhaustions": 0,
        "reasoning_escalations": 1,
        "child_fanout": 1,
        "child_cancellations": 0,
        "completion_gate_checks": 0,
        "completion_gate_rejections": 1,
        "input_tokens": 10,
        "output_tokens": 4,
        "reasoning_tokens": 2,
    }
    kinds = [child.kind for step in snapshot.root.children for child in step.children]
    assert {"tool", "worker", "validation", "repair", "reasoning"}.issubset(kinds)


def test_projection_marks_running_repair_failed_when_budget_is_exhausted() -> None:
    events = [
        _event(1, AgentRunEventType.RUN_STARTED),
        _event(
            2,
            AgentRunEventType.REPAIR_STARTED,
            step_index=1,
            payload={"repair_iteration": 1, "reason_code": "validation_failed"},
        ),
        _event(
            3,
            AgentRunEventType.REPAIR_EXHAUSTED,
            step_index=2,
            payload={"reason_code": "repair_exhausted", "repair_iterations": 1},
        ),
        _event(
            4,
            AgentRunEventType.RUN_BLOCKED,
            step_index=2,
            payload={"failure_reason": "repair_exhausted"},
        ),
    ]

    snapshot = project_run_events(
        events,
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert snapshot is not None
    repair_nodes = [
        child
        for step in snapshot.root.children
        for child in step.children
        if child.kind == "repair"
    ]
    assert [(node.label, node.status) for node in repair_nodes] == [
        ("Repairing completion requirements", "failed"),
        ("Repair budget exhausted", "failed"),
    ]
    assert snapshot.root.children[0].status == "failed"
    assert snapshot.summary.runtime_metrics["repair_exhaustions"] == 1


def test_chat_trace_read_service_prefers_canonical_run_events(tmp_path) -> None:
    db_path = tmp_path / "runtime_trace.db"
    apply_chain_schema("runtime_trace", db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO agent_run_manifests (
                run_id, turn_id, session_id, user_id, manifest_json,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "turn-1", "session-1", "user-1", "{}", 1000, 1000),
        )
        for event in (
            _event(1, AgentRunEventType.RUN_STARTED),
            _event(
                2,
                AgentRunEventType.MODEL_OUTPUT,
                step_index=1,
                payload={
                    "llm_trace": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "duration_ms": 450,
                        "input_tokens": 12,
                        "output_tokens": 2,
                        "reasoning_tokens": 1,
                        "thinking_enabled": True,
                        "thinking_depth": "low",
                    }
                },
            ),
            _event(3, AgentRunEventType.RUN_COMPLETED, step_index=1),
        ):
            connection.execute(
                """
                INSERT INTO agent_run_events (
                    event_id, run_id, sequence, turn_id, session_id, user_id,
                    event_type, step_index, payload_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.sequence,
                    event.turn_id,
                    event.session_id,
                    event.user_id,
                    event.event_type.value,
                    event.step_index,
                    json.dumps(event.payload),
                    event.created_at_ms,
                ),
            )
        connection.execute(
            """
            INSERT INTO trace_turns (
                trace_id, turn_id, session_id, user_id, status, mode,
                started_at_ms, ended_at_ms, duration_ms, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trace-1",
                "turn-1",
                "session-1",
                "user-1",
                "completed",
                "agent_loop",
                1000,
                1400,
                400,
                1000,
                1400,
            ),
        )
        connection.execute(
            """
            INSERT INTO trace_spans (
                span_id, trace_id, turn_id, parent_span_id, node_type,
                name, status, iteration, started_at_ms, ended_at_ms,
                duration_ms, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "iteration-1",
                "trace-1",
                "turn-1",
                None,
                "iteration",
                "Iteration 1",
                "completed",
                1,
                1050,
                1350,
                300,
                1050,
                1350,
            ),
        )
        connection.execute(
            """
            INSERT INTO trace_spans (
                span_id, trace_id, turn_id, parent_span_id, node_type,
                name, status, started_at_ms, ended_at_ms, duration_ms,
                created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "llm-1",
                "trace-1",
                "turn-1",
                "iteration-1",
                "llm_call",
                "gpt-test",
                "ok",
                1100,
                1300,
                200,
                1100,
                1300,
            ),
        )
        connection.execute(
            """
            INSERT INTO trace_llm_calls (
                span_id, trace_id, turn_id, provider, model,
                input_tokens, output_tokens, reasoning_tokens,
                request_preview, response_preview
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "llm-1",
                "trace-1",
                "turn-1",
                "openai",
                "gpt-test",
                12,
                2,
                1,
                "Reply only with received.",
                "Received.",
            ),
        )
        connection.execute(
            """
            INSERT INTO run_plans (
                plan_id, run_id, session_id, version, required, status,
                plan_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "plan-1",
                "run-1",
                "session-1",
                1,
                1,
                "active",
                json.dumps(
                    {
                        "plan_id": "plan-1",
                        "run_id": "run-1",
                        "session_id": "session-1",
                        "version": 1,
                        "required": True,
                        "status": "active",
                        "items": [{"id": "todo-1", "content": "Inspect", "status": "in_progress"}],
                        "created_at_ms": 1000,
                        "updated_at_ms": 1000,
                    }
                ),
                1000,
                1000,
            ),
        )
        connection.commit()

    service = ChatTraceReadService()
    service._runtime_trace_db_path = db_path

    snapshot = service.get_trace_snapshot(
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    activity = service.get_turn_activity_map(
        user_id="user-1",
        session_id="session-1",
    )

    assert snapshot is not None
    assert snapshot["mode"] == "agent_loop"
    assert snapshot["root"]["metadata"]["canonical_run_events"] is True
    assert snapshot["summary"]["plan_summary"]["steps"][0]["label"] == "Inspect"
    llm_node = snapshot["root"]["children"][0]["children"][0]
    assert llm_node["kind"] == "llm"
    assert llm_node["started_at"] == 1.1
    assert llm_node["ended_at"] == 1.3
    assert llm_node["metadata"]["duration_ms"] == 200
    assert llm_node["metadata"]["thinking_depth"] == "low"
    assert llm_node["metadata"]["request_preview"] == "Reply only with received."
    assert llm_node["metadata"]["response_preview"] == "Received."
    assert llm_node["metadata"]["input"] == {"preview": "Reply only with received."}
    assert llm_node["metadata"]["output"] == {"preview": "Received."}
    assert activity["turn-1"]["status"] == "completed"


def test_enrichment_uses_tool_call_identity_and_redacts_cancelled_drafts() -> None:
    snapshot = project_run_events(
        [
            _event(1, AgentRunEventType.RUN_STARTED),
            _event(
                2,
                AgentRunEventType.MODEL_OUTPUT,
                step_index=1,
                payload={"llm_trace": {"model": "gpt-test"}},
            ),
            _event(
                3,
                AgentRunEventType.TOOL_CALL_REQUESTED,
                step_index=1,
                payload={
                    "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {"q": "Magi"}}]
                },
            ),
            _event(
                4,
                AgentRunEventType.TOOL_RESULT,
                step_index=1,
                payload={
                    "source": "lookup",
                    "status": "succeeded",
                    "metadata": {"tool_call_id": "call-1"},
                },
            ),
            _event(5, AgentRunEventType.RUN_CANCELLED, step_index=1),
        ],
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    assert snapshot is not None

    merged = enrich_projected_trace(
        snapshot,
        spans=[
            {
                "span_id": "iteration-1",
                "node_type": "iteration",
                "name": "Iteration 1",
                "status": "completed",
                "iteration": 1,
                "started_at_ms": 1100,
                "ended_at_ms": 1500,
            },
            {
                "span_id": "llm-1",
                "parent_span_id": "iteration-1",
                "node_type": "llm_call",
                "name": "gpt-test",
                "status": "completed",
                "started_at_ms": 1150,
                "ended_at_ms": 1250,
            },
            {
                "span_id": "tool-1",
                "parent_span_id": "iteration-1",
                "node_type": "tool_call",
                "name": "lookup",
                "status": "completed",
                "started_at_ms": 1300,
                "ended_at_ms": 1400,
            },
        ],
        llm_calls=[
            {
                "span_id": "llm-1",
                "request_preview": "user request",
                "response_preview": "uncommitted response",
            }
        ],
        tool_calls=[
            {
                "span_id": "tool-1",
                "tool_call_id": "call-1",
                "tool_name": "lookup",
                "arguments_json": '{"q":"Magi"}',
                "result_preview": "tool evidence",
                "result_json": '{"answer":"found"}',
            }
        ],
    )

    assert merged == (1, 1)
    llm_node, tool_node = snapshot.root.children[0].children
    assert llm_node.metadata["request_preview"] == "user request"
    assert "response_preview" not in llm_node.metadata
    assert "output" not in llm_node.metadata
    assert llm_node.result_preview == ""
    assert tool_node.metadata["tool_call_id"] == "call-1"
    assert tool_node.metadata["result_json"] == {"answer": "found"}
    assert tool_node.result_preview == "tool evidence"


def test_projection_preserves_blocked_terminal_status() -> None:
    snapshot = project_run_events(
        [
            _event(1, AgentRunEventType.RUN_STARTED),
            _event(
                2,
                AgentRunEventType.RUN_BLOCKED,
                payload={"failure_reason": "uncertain_effect"},
            ),
        ],
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
    )

    assert snapshot is not None
    assert snapshot.status == "blocked"
    assert snapshot.root.error == "uncertain_effect"
    assert snapshot.summary.headline == "Run blocked"
