from __future__ import annotations

import json
import sqlite3

from _shared.db_schema import apply_chain_schema

from magi.agent.execution.contracts import AgentRunEvent, AgentRunEventType
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
            _event(2, AgentRunEventType.RUN_COMPLETED, step_index=1),
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
                        "items": [
                            {"id": "todo-1", "content": "Inspect", "status": "in_progress"}
                        ],
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
    assert activity["turn-1"]["status"] == "completed"


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
