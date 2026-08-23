"""ValidateNode tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, RunNode
from magi.agent.run.nodes.validate import ValidateNode


def test_validate_node_declares_node_type_validate() -> None:
    assert ValidateNode.node_type == "validate"


def test_validate_node_is_a_run_node_protocol_conformer() -> None:
    class _StubToolInvocationService:
        async def invoke(self, call, context):
            return None

    node = ValidateNode(tool_invocation_service=_StubToolInvocationService())
    assert isinstance(node, RunNode)


@pytest.mark.asyncio
async def test_validate_node_returns_done_when_verify_tool_succeeds() -> None:
    """ValidateNode invokes the verify tool with mode=changed; on
    successful result it returns NodeResult(DONE) with an
    ExecutionResult containing the verify summary as response_text."""
    from magi.tools.schema import ToolResult

    captured_calls = []

    class _StubToolInvocationService:
        async def invoke(self, call, context):
            captured_calls.append((call.name, dict(call.args)))
            return ToolResult(
                success=True,
                data={
                    "mode": "changed",
                    "results": [],
                    "summary": {"pass": 3, "fail": 0, "skipped": 0, "timeout": 0},
                },
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_invocation_service=_StubToolInvocationService())
    request = build_minimal_request_for_validate()

    result = await node.execute(request)

    assert captured_calls == [("verify", {"mode": "changed"})]
    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None
    assert "verified" in result.execution_result.response_text.lower()


@pytest.mark.asyncio
async def test_validate_node_returns_failed_when_verify_tool_reports_file_errors() -> None:
    """When verify reports file-level failures (summary.fail > 0), ValidateNode
    returns NodeResult(FAILED) with the failed file paths surfaced."""
    from magi.tools.schema import ToolResult

    class _StubToolInvocationService:
        async def invoke(self, call, context):
            return ToolResult(
                success=True,
                data={
                    "mode": "changed",
                    "results": [
                        {"path": "bar.py", "status": "fail"},
                        {"path": "baz.py", "status": "fail"},
                    ],
                    "summary": {"pass": 0, "fail": 2, "skipped": 0, "timeout": 0},
                },
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_invocation_service=_StubToolInvocationService())
    request = build_minimal_request_for_validate()

    result = await node.execute(request)

    assert result.outcome == NodeOutcome.FAILED
    assert "verification failed" in (result.error or "").lower()
    assert "bar.py" in (result.error or "")


@pytest.mark.asyncio
async def test_validate_node_returns_failed_when_tool_itself_fails() -> None:
    """When the verify tool returns success=False (internal crash, bad mode, etc.),
    ValidateNode returns NodeResult(FAILED) with the tool's error."""
    from magi.tools.schema import ToolResult

    class _StubToolInvocationService:
        async def invoke(self, call, context):
            return ToolResult(
                success=False,
                error="bad mode arg",
                error_code="INVALID_MODE",
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_invocation_service=_StubToolInvocationService())
    request = build_minimal_request_for_validate()

    result = await node.execute(request)

    assert result.outcome == NodeOutcome.FAILED
    assert "bad mode arg" in (result.error or "")


@pytest.mark.asyncio
async def test_validate_node_returns_done_when_no_files_changed() -> None:
    """If verify returns a no-changes-detected result (all zeros), validate has
    nothing to do and returns DONE with a short note. This handles the
    case where a coding turn was just a conversation with no edits."""
    from magi.tools.schema import ToolResult

    class _StubToolInvocationService:
        async def invoke(self, call, context):
            return ToolResult(
                success=True,
                data={
                    "mode": "changed",
                    "results": [],
                    "summary": {"pass": 0, "fail": 0, "skipped": 0, "timeout": 0},
                },
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_invocation_service=_StubToolInvocationService())
    request = build_minimal_request_for_validate()
    result = await node.execute(request)

    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None
    assert "no files changed" in result.execution_result.response_text.lower()


@pytest.mark.asyncio
async def test_validate_node_builds_tool_execution_context() -> None:
    """_build_tool_context returns a ToolExecutionContext (Pydantic model),
    not a plain dict. VerifyTool reads context.env_vars and context.workspace."""
    from magi.tools.schema import ToolExecutionContext, ToolResult

    received_contexts = []

    class _StubToolInvocationService:
        async def invoke(self, call, context):
            received_contexts.append(context)
            return ToolResult(
                success=True,
                data={
                    "mode": "changed",
                    "results": [],
                    "summary": {"pass": 1, "fail": 0, "skipped": 0, "timeout": 0},
                },
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_invocation_service=_StubToolInvocationService())
    request = build_minimal_request_for_validate()
    await node.execute(request)

    assert len(received_contexts) == 1
    ctx = received_contexts[0].execution_context
    assert isinstance(ctx, ToolExecutionContext), (
        f"Expected ToolExecutionContext, got {type(ctx)}"
    )
    assert ctx.env_vars.get("session_id") == "session_validate"
    assert ctx.workspace == "/tmp/validate_workspace"


@pytest.mark.asyncio
async def test_validate_node_handles_tool_exception_as_failed() -> None:
    """If the verify tool itself raises, ValidateNode returns FAILED."""

    class _RaisingInvocationService:
        async def invoke(self, call, context):
            raise RuntimeError("tool invocation boom")

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_invocation_service=_RaisingInvocationService())
    request = build_minimal_request_for_validate()
    result = await node.execute(request)

    assert result.outcome == NodeOutcome.FAILED
    assert "tool invocation boom" in (result.error or "")


@pytest.mark.asyncio
async def test_validate_node_uses_canonical_pre_tool_hook() -> None:
    from unittest.mock import AsyncMock, patch

    from magi.agent.execution.tool_invocation_service import ToolInvocationService
    from magi.hooks.contracts import HookDecision

    class _Registry:
        execute = AsyncMock()

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    registry = _Registry()
    node = ValidateNode(
        tool_invocation_service=ToolInvocationService(registry),
    )
    with patch(
        "magi.hooks.dispatch.dispatch_hook",
        new=AsyncMock(return_value=HookDecision.deny("validation blocked")),
    ):
        result = await node.execute(build_minimal_request_for_validate())

    registry.execute.assert_not_awaited()
    assert result.outcome == NodeOutcome.FAILED
    assert result.error == "validation blocked"
