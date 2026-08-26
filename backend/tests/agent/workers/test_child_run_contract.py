"""Focused contract tests for bounded child agent runs."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from magi.agent.background.contracts import BackgroundTask, BackgroundTaskStatus
from magi.agent.execution.reasoning import (
    ReasoningPolicy,
    ReasoningPreference,
    ReasoningState,
)
from magi.agent.runtime_tools.agent_tool import AgentTool
from magi.agent.workers.child_preset import (
    ChildRunPreset,
    parse_child_preset,
    resolve_child_reasoning_policy,
    resolve_child_tools,
)
from magi.agent.workers.worker_manager import ChildRunCoordinator
from magi.agent.workers.worker_state import WorkerRunState
from magi.config.models import ThinkingDepth
from magi.tools.schema import ToolExecutionContext


class _Tool:
    def __init__(self, name: str, effect_class: str) -> None:
        self._schema = SimpleNamespace(
            name=name,
            effect_class=effect_class,
            effect_replay_policy=(
                "read_only" if effect_class == "read_only" else "reconcilable"
            ),
            dangerous=effect_class == "destructive",
            requires_auth=False,
            metadata={},
        )

    def get_schema(self):
        return self._schema


class _Registry:
    def __init__(self) -> None:
        self._tools = {
            "inspect": _Tool("inspect", "read_only"),
            "write_file": _Tool("write_file", "local_write"),
            "publish": _Tool("publish", "external_write"),
            "delete": _Tool("delete", "destructive"),
            "unclassified": _Tool("unclassified", "unknown"),
            "agent": _Tool("agent", "external_write"),
            "todo_write": _Tool("todo_write", "local_write"),
        }

    def list_tools(self) -> list[str]:
        return list(self._tools)

    def get_tool(self, name: str):
        return self._tools.get(name)


def _state(
    *,
    status: str = "running",
    ownership: str = "parent",
    owner_run_id: str | None = "run-parent",
) -> WorkerRunState:
    now = time.time()
    return WorkerRunState(
        worker_id="worker-1",
        child_run_id="child-1",
        preset=ChildRunPreset.READ_ONLY,
        description="inspect runtime",
        prompt="Inspect the runtime",
        parent_task_agent_type="chat",
        parent_task_agent_id="user-1",
        target_task_agent_type="chat",
        target_task_agent_id="user-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        created_at=now,
        parent_run_id="run-parent",
        ownership=ownership,
        owner_run_id=owner_run_id,
        status=status,
        updated_at=now,
    )


def _context(*, run_id: str = "run-parent", session_id: str = "session-1"):
    return ToolExecutionContext(
        agent_id="chat:user-1",
        workspace="/workspace",
        env_vars={"run_id": run_id, "session_id": session_id},
    )


def test_public_presets_are_exact_and_do_not_accept_retired_aliases() -> None:
    assert parse_child_preset("read_only") is ChildRunPreset.READ_ONLY
    assert parse_child_preset("workspace_write") is ChildRunPreset.WORKSPACE_WRITE
    assert parse_child_preset("CodeExplore") is None
    assert parse_child_preset("general-purpose") is None

    names = {parameter.name for parameter in AgentTool().schema.parameters}
    assert "preset" in names
    assert "subagent_type" not in names


def test_child_tool_scope_is_derived_from_effect_metadata() -> None:
    registry = _Registry()

    assert resolve_child_tools(registry, ChildRunPreset.READ_ONLY) == ["inspect"]
    assert resolve_child_tools(registry, ChildRunPreset.REVIEW) == ["inspect"]
    assert resolve_child_tools(registry, ChildRunPreset.WORKSPACE_WRITE) == [
        "inspect",
        "write_file",
    ]


def test_child_reasoning_is_bounded_by_parent_and_remaining_escalations() -> None:
    fast_parent = ReasoningPolicy.from_preference(ReasoningPreference.FAST)
    fast_child = resolve_child_reasoning_policy(
        preset=ChildRunPreset.REVIEW,
        parent_policy=fast_parent,
        parent_state=ReasoningState.start(fast_parent),
    )
    assert fast_child.initial_depth is ThinkingDepth.LOW
    assert fast_child.maximum_depth is ThinkingDepth.LOW

    parent = ReasoningPolicy.from_preference(ReasoningPreference.AUTO)
    state = ReasoningState.start(parent)
    assert state.escalate(parent, reason="validation_failed")
    child = resolve_child_reasoning_policy(
        preset=ChildRunPreset.REVIEW,
        parent_policy=parent,
        parent_state=state,
    )
    assert child.initial_depth is ThinkingDepth.MEDIUM
    assert child.maximum_depth is ThinkingDepth.HIGH
    assert child.max_escalations == 1


def test_child_environment_omits_exact_wall_clock_time() -> None:
    coordinator = ChildRunCoordinator()

    rules = coordinator._build_worker_environment_rules("/workspace")

    assert "- Local date:" in rules
    assert "- Timezone:" in rules
    assert "current_time tool" in rules
    assert "Current local time:" not in rules


@pytest.mark.asyncio
async def test_targeted_cancel_requires_parent_ownership_and_lineage() -> None:
    coordinator = ChildRunCoordinator()
    running = _state()
    running.task = asyncio.create_task(asyncio.sleep(60))
    coordinator._runs[running.worker_id] = running

    wrong_parent = await coordinator._cancel_worker(
        running.worker_id,
        _context(run_id="other-run"),
    )
    assert not wrong_parent.success
    assert running.status == "running"

    cancelled = await coordinator._cancel_worker(running.worker_id, _context())
    assert cancelled.success
    assert running.status == "cancelled"
    assert cancelled.data["evidence"]["evidence_id"] == "child:child-1"

    repeated = await coordinator._cancel_worker(running.worker_id, _context())
    assert repeated.success
    assert repeated.data["status"] == "cancelled"


@pytest.mark.asyncio
async def test_background_child_launch_transfers_to_durable_runtime() -> None:
    class _BackgroundManager:
        def __init__(self) -> None:
            self.spec = None

        async def enqueue(self, spec):
            self.spec = spec
            task = BackgroundTask.new(spec)
            task.status = BackgroundTaskStatus.PENDING
            return task

    manager = _BackgroundManager()
    coordinator = ChildRunCoordinator()
    coordinator._background_task_manager = manager
    coordinator._tool_registry = _Registry()
    policy = ReasoningPolicy.from_preference(ReasoningPreference.AUTO)
    context = ToolExecutionContext(
        agent_id="chat:user-1",
        workspace="/workspace",
        env_vars={
            "user_id": "user-1",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "run_id": "run-parent",
            "run_revision": "2",
            "parent_reasoning_policy": json.dumps(policy.to_dict()),
            "parent_reasoning_state": json.dumps(ReasoningState.start(policy).to_dict()),
        },
    )

    result = await coordinator._launch_background_child(
        {
            "preset": "read_only",
            "description": "inspect runtime",
            "prompt": "Inspect the runtime",
            "run_in_background": True,
        },
        context,
    )

    assert result.success
    assert result.data["ownership"] == "background"
    assert result.data["parent_run_id"] == "run-parent"
    assert manager.spec.execution_preset == "child_read_only"
    assert manager.spec.parent_run_id == "run-parent"
    assert manager.spec.selected_tools == ["inspect"]
    assert manager.spec.final_response_json_mode is True


def test_workspace_write_result_requires_artifacts_and_passing_verification() -> None:
    coordinator = ChildRunCoordinator()
    base = {
        "result_status": "success",
        "summary": "Updated the runtime",
        "findings": [],
        "evidence": [],
        "records": [],
        "gaps": [],
        "next_steps": [],
        "artifacts": [{"path": "src/runtime.py", "operation": "modified"}],
        "verification": [
            {"command": "pytest tests/runtime", "status": "passed", "detail": "12 passed"}
        ],
    }
    result = coordinator._validate_worker_result(
        ChildRunPreset.WORKSPACE_WRITE,
        json.dumps(base),
    )
    assert result.artifacts[0].path == "src/runtime.py"

    base["verification"] = []
    with pytest.raises(ValueError, match="require artifacts and verification"):
        coordinator._validate_worker_result(
            ChildRunPreset.WORKSPACE_WRITE,
            json.dumps(base),
        )
