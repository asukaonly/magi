"""Phase E end-to-end smoke: detach mid-multi-node, resume from snapshot."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, NodeResult
from magi.agent.run.registry import NodeRegistry
from magi.agent.run.runner import NodeSequenceRunner
from magi.agent.run.snapshot import RunSnapshot
from magi.agent.run.spec import NodeSpec


class _StubNode:
    def __init__(self, node_type: str, *, snapshot_dict=None,
                 outcome=NodeOutcome.DONE, response_text=None, error=None) -> None:
        self.node_type = node_type
        self._snapshot_dict = snapshot_dict or {}
        self._outcome = outcome
        self._response = response_text
        self._error = error
        self.executed = False
        self.restored_state = None

    async def execute(self, request):
        from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult
        self.executed = True
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


@pytest.mark.asyncio
async def test_detach_after_tool_loop_resume_skips_to_validate() -> None:
    """Full Phase E story:
    1. Build registry with tool_loop + validate.
    2. Run sequence; tool_loop captures state via snapshot.
    3. Stop the run after tool_loop (simulate detach).
    4. Build a fresh runner + nodes (different instances).
    5. Resume with the captured snapshot; tool_loop's restore is called
       but it doesn't re-execute; validate runs from scratch.
    """
    tool_loop_1 = _StubNode("tool_loop", snapshot_dict={"messages": [], "iterations": 5},
                            response_text="tool loop done")
    validate_1 = _StubNode("validate", response_text="should be skipped")
    registry_1 = NodeRegistry()
    registry_1.register(tool_loop_1)
    registry_1.register(validate_1)
    runner_1 = NodeSequenceRunner(node_registry=registry_1)

    # Step 1: run ONLY the first node by passing a single-element sequence
    # to simulate the "detach after tool_loop, validate not yet started" state.
    _result1, snapshot_after_tool_loop = await runner_1.run_with_snapshot(
        run_id="r_detach",
        node_specs=[NodeSpec(node_type="tool_loop")],
        request=object(),
    )

    # snapshot has cursor=1 (the single node completed) with tool_loop state.
    assert snapshot_after_tool_loop.cursor == 1
    assert snapshot_after_tool_loop.node_states["tool_loop"] == {
        "messages": [], "iterations": 5,
    }

    # Step 2: simulate the background dispatcher creating fresh nodes and
    # resuming with the full sequence + the snapshot.
    # The snapshot's graph is just ("tool_loop",), but on resume we know
    # the FULL sequence is (tool_loop, validate) — so we re-issue the full
    # node_specs and re-author the snapshot to keep cursor=1 against the
    # full graph.
    tool_loop_2 = _StubNode("tool_loop", response_text="must not re-run")
    validate_2 = _StubNode("validate", response_text="validate ran on resume")
    registry_2 = NodeRegistry()
    registry_2.register(tool_loop_2)
    registry_2.register(validate_2)
    runner_2 = NodeSequenceRunner(node_registry=registry_2)

    # Build the resume snapshot against the full graph.
    full_resume_snapshot = RunSnapshot(
        run_id="r_detach",
        graph=("tool_loop", "validate"),
        cursor=1,
        node_states=snapshot_after_tool_loop.node_states,
    )

    result2, snapshot_final = await runner_2.run_with_snapshot(
        run_id="r_detach",
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
        resume_from=full_resume_snapshot,
    )

    # tool_loop did NOT re-execute (its execute() was not called), but its
    # restore was called with the prior state.
    assert tool_loop_2.executed is False
    assert tool_loop_2.restored_state == {"messages": [], "iterations": 5}

    # validate DID run.
    assert validate_2.executed is True
    assert result2 is not None
    assert "validate ran on resume" in result2.response_text
    assert snapshot_final.cursor == 2


@pytest.mark.asyncio
async def test_resume_into_a_run_that_failed_partway_can_retry_failed_node() -> None:
    """If a snapshot was captured with cursor pointing at a failed node,
    a subsequent resume runs that node again from scratch (its restore
    gets the pre-failure state, then its execute runs)."""
    tool_loop = _StubNode("tool_loop", response_text="primary done")
    validate_first = _StubNode("validate", outcome=NodeOutcome.FAILED, error="boom 1")
    registry_1 = NodeRegistry()
    registry_1.register(tool_loop)
    registry_1.register(validate_first)
    runner_1 = NodeSequenceRunner(node_registry=registry_1)

    _result, snapshot_after_failure = await runner_1.run_with_snapshot(
        run_id="r_retry",
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
    )

    # cursor stays at the failed node (1).
    assert snapshot_after_failure.cursor == 1

    # Re-author registry: validate now succeeds (simulated retry).
    tool_loop_2 = _StubNode("tool_loop", response_text="should not re-run")
    validate_second = _StubNode("validate", response_text="ok on retry")
    registry_2 = NodeRegistry()
    registry_2.register(tool_loop_2)
    registry_2.register(validate_second)
    runner_2 = NodeSequenceRunner(node_registry=registry_2)

    result_retry, snapshot_complete = await runner_2.run_with_snapshot(
        run_id="r_retry",
        node_specs=[NodeSpec(node_type="tool_loop"), NodeSpec(node_type="validate")],
        request=object(),
        resume_from=snapshot_after_failure,
    )

    assert tool_loop_2.executed is False
    assert validate_second.executed is True
    assert "ok on retry" in result_retry.response_text
    assert snapshot_complete.cursor == 2
