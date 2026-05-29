"""ValidateNode tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, RunNode
from magi.agent.run.nodes.validate import ValidateNode


def test_validate_node_declares_node_type_validate() -> None:
    assert ValidateNode.node_type == "validate"


def test_validate_node_is_a_run_node_protocol_conformer() -> None:
    class _StubToolRegistry:
        def execute_tool(self, tool_name, params, context):
            return None

    node = ValidateNode(tool_registry=_StubToolRegistry())
    assert isinstance(node, RunNode)


@pytest.mark.asyncio
async def test_validate_node_returns_done_when_verify_tool_succeeds() -> None:
    """ValidateNode invokes the verify tool with mode=changed; on
    successful result it returns NodeResult(DONE) with an
    ExecutionResult containing the verify summary as response_text."""
    from magi.tools.schema import ToolResult

    captured_calls = []

    class _StubToolRegistry:
        async def execute_tool(self, *, tool_name, params, context):
            captured_calls.append((tool_name, params))
            return ToolResult(
                success=True,
                data={"summary": "All 3 files verified OK"},
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_registry=_StubToolRegistry())
    request = build_minimal_request_for_validate()

    result = await node.execute(request)

    assert captured_calls == [("verify", {"mode": "changed"})]
    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None
    assert "verified" in result.execution_result.response_text.lower()


@pytest.mark.asyncio
async def test_validate_node_returns_failed_when_verify_tool_reports_errors() -> None:
    """When verify reports compilation/parse errors, ValidateNode
    returns NodeResult(FAILED) with the errors surfaced."""
    from magi.tools.schema import ToolResult

    class _StubToolRegistry:
        async def execute_tool(self, *, tool_name, params, context):
            return ToolResult(
                success=False,
                data={"errors": ["foo.py: syntax error at line 5"]},
                error="Verification failed: 1 file has errors",
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_registry=_StubToolRegistry())
    request = build_minimal_request_for_validate()

    result = await node.execute(request)

    assert result.outcome == NodeOutcome.FAILED
    assert "verification failed" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_validate_node_returns_done_when_no_files_changed() -> None:
    """If verify returns a no-changes-detected result, validate has
    nothing to do and returns DONE with a short note. This handles the
    case where a coding turn was just a conversation with no edits."""
    from magi.tools.schema import ToolResult

    class _StubToolRegistry:
        async def execute_tool(self, *, tool_name, params, context):
            return ToolResult(
                success=True,
                data={"summary": "No files changed in this session", "changed_count": 0},
            )

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_registry=_StubToolRegistry())
    request = build_minimal_request_for_validate()
    result = await node.execute(request)

    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None


@pytest.mark.asyncio
async def test_validate_node_handles_tool_exception_as_failed() -> None:
    """If the verify tool itself raises, ValidateNode returns FAILED."""

    class _RaisingRegistry:
        async def execute_tool(self, *, tool_name, params, context):
            raise RuntimeError("tool registry boom")

    from agent.fixtures_validate_node import build_minimal_request_for_validate

    node = ValidateNode(tool_registry=_RaisingRegistry())
    request = build_minimal_request_for_validate()
    result = await node.execute(request)

    assert result.outcome == NodeOutcome.FAILED
    assert "tool registry boom" in (result.error or "")
