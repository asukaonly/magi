"""ReplyNode adapter tests."""
from __future__ import annotations

import pytest

from magi.agent.run.nodes.protocol import NodeOutcome, RunNode
from magi.agent.run.nodes.reply import ReplyNode


def test_reply_node_declares_node_type_reply() -> None:
    assert ReplyNode.node_type == "reply"


def test_reply_node_is_a_run_node_protocol_conformer() -> None:
    from agent.fixtures_direct_handler import build_direct_handler_with_simple_call

    handler, _ps, _ = build_direct_handler_with_simple_call(response_text="x")
    node = ReplyNode(direct_llm_handler=handler)
    assert isinstance(node, RunNode)


@pytest.mark.asyncio
async def test_reply_node_delegates_to_direct_handler_and_wraps_result() -> None:
    from agent.fixtures_direct_handler import (
        build_direct_handler_with_simple_call,
        build_minimal_direct_request,
    )
    from magi.control.run_control import null_run_control

    handler, _ps, _calls = build_direct_handler_with_simple_call(response_text="hi from handler")
    node = ReplyNode(direct_llm_handler=handler)

    request = build_minimal_direct_request(
        control=null_run_control(), streaming_enabled=False,
    )
    result = await node.execute(request)

    assert result.outcome == NodeOutcome.DONE
    assert result.execution_result is not None
    assert result.execution_result.response_text == "hi from handler"


@pytest.mark.asyncio
async def test_reply_node_propagates_handler_exception_as_failed() -> None:
    from agent.fixtures_direct_handler import build_minimal_direct_request
    from magi.control.run_control import null_run_control

    class _RaisingHandler:
        async def execute(self, request):
            raise RuntimeError("simulated handler failure")

    node = ReplyNode(direct_llm_handler=_RaisingHandler())
    request = build_minimal_direct_request(
        control=null_run_control(), streaming_enabled=False,
    )
    result = await node.execute(request)

    assert result.outcome == NodeOutcome.FAILED
    assert "simulated handler failure" in (result.error or "")
