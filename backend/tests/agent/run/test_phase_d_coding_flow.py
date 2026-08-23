"""Phase D Task 5: TaskAgentExecutionEngine uses NodeSequenceRunner
for user-message paths; profile=coding auto-appends ValidateNode."""
from __future__ import annotations

import inspect

import pytest


def test_execution_engine_constructs_validate_node_in_init() -> None:
    """TaskAgentExecutionEngine must construct a ValidateNode and register
    it on the NodeRegistry."""
    from magi.agent.run.execution_engine import TaskAgentExecutionEngine

    src = inspect.getsource(TaskAgentExecutionEngine)
    assert "ValidateNode" in src, (
        "TaskAgentExecutionEngine must construct a ValidateNode"
    )


def test_execution_engine_constructs_graph_builder_and_runner() -> None:
    """TaskAgentExecutionEngine.__init__ must construct a GraphBuilder
    and a NodeSequenceRunner."""
    from magi.agent.run.execution_engine import TaskAgentExecutionEngine

    src = inspect.getsource(TaskAgentExecutionEngine.__init__)
    assert "GraphBuilder" in src
    assert "NodeSequenceRunner" in src


def test_execution_engine_execute_uses_node_sequence_runner() -> None:
    """TaskAgentExecutionEngine.execute must dispatch user-message
    paths through NodeSequenceRunner.run; single-node fallback for
    legacy single-Node paths is acceptable but the multi-node path
    must go through the runner."""
    from magi.agent.run.execution_engine import TaskAgentExecutionEngine

    src = inspect.getsource(TaskAgentExecutionEngine.execute)
    assert "_node_sequence_runner" in src or "node_sequence_runner" in src or "_runner" in src, (
        "execute() must use the NodeSequenceRunner"
    )
    assert "build_node_sequence" in src or "_graph_builder" in src, (
        "execute() must build node sequence via GraphBuilder"
    )

@pytest.mark.asyncio
async def test_coding_profile_runs_tool_loop_then_validate_end_to_end() -> None:
    """The full Phase D promise: a coding profile RouteDecision causes
    the NodeSequenceRunner to run ToolLoopNode followed by ValidateNode,
    and the final ExecutionResult carries both outputs."""
    from magi.agent.run.builder import GraphBuilder
    from magi.agent.run.nodes.plan_fanout import PlanFanoutNode
    from magi.agent.run.nodes.reply import ReplyNode
    from magi.agent.run.nodes.tool_loop import ToolLoopNode
    from magi.agent.run.nodes.validate import ValidateNode
    from magi.agent.run.registry import NodeRegistry
    from magi.agent.run.runner import NodeSequenceRunner
    from magi.agent.execution.tool_invocation_service import ToolInvocationService
    from magi.agent.task_agents.common.contracts import (
        ExecutionMode,
        FunctionCallingExecutionResult,
    )
    from magi.tools.schema import ToolResult
    from magi.tools.context_routing import RouteDecision

    class _StubFCHandler:
        async def execute(self, request):
            return FunctionCallingExecutionResult(
                mode=ExecutionMode.FUNCTION_CALLING,
                response_text="Applied 2 edits to foo.py",
                execution_outcome={"status": "completed", "iterations": 3},
            )

    class _StubToolRegistry:
        async def execute(self, tool_name, parameters, context):
            return ToolResult(
                success=True,
                data={
                    "mode": "changed",
                    "results": [{"path": "foo.py", "status": "pass"}],
                    "summary": {"pass": 1, "fail": 0, "skipped": 0, "timeout": 0},
                },
            )

    registry = NodeRegistry()
    registry.register(ReplyNode(direct_llm_handler=_StubFCHandler()))
    registry.register(ToolLoopNode(function_calling_handler=_StubFCHandler()))
    registry.register(PlanFanoutNode(orchestration_launch_handler=_StubFCHandler()))
    registry.register(
        ValidateNode(
            tool_invocation_service=ToolInvocationService(_StubToolRegistry()),
        )
    )

    builder = GraphBuilder()
    runner = NodeSequenceRunner(node_registry=registry)

    coding_decision = RouteDecision(
        profile="coding", graph_shape="tool_loop", complexity="medium",
        may_write=True,
    )
    node_specs = builder.build_node_sequence(coding_decision)
    assert [s.node_type for s in node_specs] == ["tool_loop", "validate"]

    result = await runner.run(node_specs=node_specs, request=object())  # type: ignore[arg-type]

    assert result is not None
    assert "Applied 2 edits" in result.response_text
    assert "verified" in result.response_text.lower()


@pytest.mark.asyncio
async def test_coding_profile_validation_failure_surfaces_both_outputs() -> None:
    """When validation FAILS after a successful primary run, the user
    sees both the primary node's success message AND the validation error."""
    from magi.agent.run.builder import GraphBuilder
    from magi.agent.run.nodes.plan_fanout import PlanFanoutNode
    from magi.agent.run.nodes.reply import ReplyNode
    from magi.agent.run.nodes.tool_loop import ToolLoopNode
    from magi.agent.run.nodes.validate import ValidateNode
    from magi.agent.run.registry import NodeRegistry
    from magi.agent.run.runner import NodeSequenceRunner
    from magi.agent.execution.tool_invocation_service import ToolInvocationService
    from magi.agent.task_agents.common.contracts import (
        ExecutionMode, FunctionCallingExecutionResult,
    )
    from magi.tools.schema import ToolResult
    from magi.tools.context_routing import RouteDecision

    class _StubFCHandler:
        async def execute(self, request):
            return FunctionCallingExecutionResult(
                mode=ExecutionMode.FUNCTION_CALLING,
                response_text="Applied 1 edit to bar.py",
                execution_outcome={"status": "completed", "iterations": 1},
            )

    class _ValidateFailRegistry:
        async def execute(self, tool_name, parameters, context):
            return ToolResult(
                success=True,
                data={
                    "mode": "changed",
                    "results": [{"path": "bar.py", "status": "fail"}],
                    "summary": {"pass": 0, "fail": 1, "skipped": 0, "timeout": 0},
                },
            )

    registry = NodeRegistry()
    registry.register(ReplyNode(direct_llm_handler=_StubFCHandler()))
    registry.register(ToolLoopNode(function_calling_handler=_StubFCHandler()))
    registry.register(PlanFanoutNode(orchestration_launch_handler=_StubFCHandler()))
    registry.register(
        ValidateNode(
            tool_invocation_service=ToolInvocationService(_ValidateFailRegistry()),
        )
    )

    builder = GraphBuilder()
    runner = NodeSequenceRunner(node_registry=registry)

    coding_decision = RouteDecision(
        profile="coding", graph_shape="tool_loop", complexity="medium", may_write=True,
    )
    node_specs = builder.build_node_sequence(coding_decision)

    result = await runner.run(node_specs=node_specs, request=object())  # type: ignore[arg-type]

    assert result is not None
    # Primary success surfaced
    assert "Applied 1 edit" in result.response_text
    # Validation error surfaced
    assert "bar.py" in result.response_text
    assert "[error]" in result.response_text


@pytest.mark.asyncio
async def test_non_coding_profile_runs_single_node_no_validate() -> None:
    """A chat-profile turn runs ONLY the primary node — ValidateNode
    must not be invoked for non-coding profiles even if registered."""
    from magi.agent.run.builder import GraphBuilder
    from magi.agent.run.nodes.plan_fanout import PlanFanoutNode
    from magi.agent.run.nodes.reply import ReplyNode
    from magi.agent.run.nodes.tool_loop import ToolLoopNode
    from magi.agent.run.nodes.validate import ValidateNode
    from magi.agent.run.registry import NodeRegistry
    from magi.agent.run.runner import NodeSequenceRunner
    from magi.agent.execution.tool_invocation_service import ToolInvocationService
    from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult
    from magi.tools.context_routing import RouteDecision

    validate_calls = []

    class _AssertNotCalledValidate:
        async def execute(self, tool_name, parameters, context):
            validate_calls.append((tool_name, parameters))
            raise AssertionError("ValidateNode must not be invoked for chat profile")

    class _StubDirect:
        async def execute(self, request):
            return ExecutionResult(
                mode=ExecutionMode.DIRECT_LLM, response_text="hi there",
            )

    class _StubFC:
        async def execute(self, request):
            return ExecutionResult(
                mode=ExecutionMode.FUNCTION_CALLING, response_text="tool!",
            )

    class _StubOrch:
        async def execute(self, request):
            return ExecutionResult(
                mode=ExecutionMode.ORCHESTRATION_LAUNCH, response_text="orch!",
            )

    registry = NodeRegistry()
    registry.register(ReplyNode(direct_llm_handler=_StubDirect()))
    registry.register(ToolLoopNode(function_calling_handler=_StubFC()))
    registry.register(PlanFanoutNode(orchestration_launch_handler=_StubOrch()))
    registry.register(
        ValidateNode(
            tool_invocation_service=ToolInvocationService(_AssertNotCalledValidate()),
        )
    )

    builder = GraphBuilder()
    runner = NodeSequenceRunner(node_registry=registry)

    chat_decision = RouteDecision(profile="chat", graph_shape="reply", complexity="simple")
    node_specs = builder.build_node_sequence(chat_decision)
    assert node_specs == [type(node_specs[0])(node_type="reply")]

    result = await runner.run(node_specs=node_specs, request=object())  # type: ignore[arg-type]

    assert result is not None
    assert result.response_text == "hi there"
    assert validate_calls == []


def test_execution_engine_uses_run_with_snapshot_when_session_run_id_available() -> None:
    """Phase E: TaskAgentExecutionEngine.execute calls
    NodeSequenceRunner.run_with_snapshot and saves the returned snapshot."""
    import inspect
    from magi.agent.run.execution_engine import TaskAgentExecutionEngine

    src = inspect.getsource(TaskAgentExecutionEngine.execute)
    assert "run_with_snapshot" in src, (
        "execute() must use run_with_snapshot to persist per-turn state"
    )
    assert "_save_snapshot" in src, (
        "execute() must save the returned snapshot through its store seam"
    )
