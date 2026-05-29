"""NodeSequenceRunner persistence tests (Phase E)."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, NodeResult
from magi.agent.run.registry import NodeRegistry
from magi.agent.run.runner import NodeSequenceRunner
from magi.agent.run.snapshot import RunSnapshot
from magi.agent.run.spec import NodeSpec


class _StubNode:
    def __init__(self, node_type: str, snapshot_dict: dict | None = None,
                 outcome: NodeOutcome = NodeOutcome.DONE,
                 response_text: str | None = None,
                 error: str | None = None) -> None:
        self.node_type = node_type
        self._snapshot_dict = snapshot_dict or {}
        self._outcome = outcome
        self._response = response_text
        self._error = error
        self.restored_state: dict | None = None

    async def execute(self, request):
        from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult
        if self._outcome == NodeOutcome.FAILED:
            return NodeResult(outcome=NodeOutcome.FAILED, error=self._error)
        exec_result = (
            ExecutionResult(mode=ExecutionMode.DIRECT_LLM, response_text=self._response)
            if self._response is not None
            else None
        )
        return NodeResult(outcome=self._outcome, execution_result=exec_result)

    def snapshot(self) -> dict:
        return dict(self._snapshot_dict)

    def restore(self, state: dict) -> None:
        self.restored_state = dict(state)


def _build_registry(*nodes) -> NodeRegistry:
    registry = NodeRegistry()
    for n in nodes:
        registry.register(n)
    return registry


@pytest.mark.asyncio
async def test_runner_returns_completed_run_snapshot_after_all_nodes_done() -> None:
    """After running tool_loop + validate to DONE, the returned snapshot
    has cursor == 2 (all done) and node_states populated."""
    primary = _StubNode("tool_loop", snapshot_dict={"messages": [], "iterations": 3},
                        response_text="primary done")
    validate = _StubNode("validate", response_text="[verify] OK")
    registry = _build_registry(primary, validate)
    runner = NodeSequenceRunner(node_registry=registry)
    result, snapshot = await runner.run_with_snapshot(
        run_id="r1",
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
    )
    assert result is not None
    assert isinstance(snapshot, RunSnapshot)
    assert snapshot.run_id == "r1"
    assert snapshot.graph == ("tool_loop", "validate")
    assert snapshot.cursor == 2  # both nodes completed
    assert snapshot.node_states["tool_loop"] == {"messages": [], "iterations": 3}


@pytest.mark.asyncio
async def test_runner_returns_partial_snapshot_when_node_fails_mid_sequence() -> None:
    """If validate FAILS, the returned snapshot has cursor == 1 (failed
    node still pending) and tool_loop's state is preserved."""
    primary = _StubNode("tool_loop", snapshot_dict={"messages": [], "iterations": 1},
                        response_text="primary done")
    validate = _StubNode("validate", outcome=NodeOutcome.FAILED,
                         error="syntax error")
    registry = _build_registry(primary, validate)
    runner = NodeSequenceRunner(node_registry=registry)
    _result, snapshot = await runner.run_with_snapshot(
        run_id="r2",
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
    )
    assert snapshot.cursor == 1  # tool_loop done; validate failed (still at cursor=1)
    assert "tool_loop" in snapshot.node_states


@pytest.mark.asyncio
async def test_runner_resumes_from_snapshot_skipping_completed_nodes() -> None:
    """When resume_from is supplied with cursor=1 and tool_loop state
    pre-populated, the runner restores tool_loop's state but does NOT
    re-execute it; runs validate from scratch."""
    primary = _StubNode("tool_loop", response_text="should not re-run")
    validate = _StubNode("validate", response_text="[verify] OK on resume")
    registry = _build_registry(primary, validate)
    runner = NodeSequenceRunner(node_registry=registry)

    resume_snapshot = RunSnapshot(
        run_id="r3",
        graph=("tool_loop", "validate"),
        cursor=1,
        node_states={"tool_loop": {"messages": [], "iterations": 3}},
    )

    result, snapshot = await runner.run_with_snapshot(
        run_id="r3",
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
        resume_from=resume_snapshot,
    )

    # tool_loop must have received its restored state via restore()
    assert primary.restored_state == {"messages": [], "iterations": 3}
    # validate ran and produced its output
    assert result is not None
    assert "[verify] OK on resume" in result.response_text
    assert snapshot.cursor == 2


@pytest.mark.asyncio
async def test_runner_legacy_run_method_still_works() -> None:
    """The Phase D run() method (no snapshot kwarg) continues to work
    for callers that don't need persistence."""
    primary = _StubNode("tool_loop", response_text="legacy")
    registry = _build_registry(primary)
    runner = NodeSequenceRunner(node_registry=registry)
    result = await runner.run(
        node_specs=[NodeSpec(node_type="tool_loop")],
        request=object(),
    )
    assert result is not None
    assert result.response_text == "legacy"
