"""Coordinator delivery integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.agent.task_agents.common import ExecutionHandlerRegistry, ExecutionResult
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator
from magi.chat.task_agent.fact_classifier import ChatFactClassifier
from magi.delivery.contracts import DeliveryFanoutResult
from magi.tools.registry import ToolRegistry
from magi_plugin_sdk.delivery import DeliveryContent


@pytest.mark.asyncio
async def test_coordinator_request_execution_defers_final_delivery_to_postprocess() -> None:
    """Execution returns its result; only the postprocess entry point sends it."""
    outcome = ExecutionResult(mode=None, response_text="final answer")
    handler = SimpleNamespace(execute=AsyncMock(return_value=outcome))
    delivered = DeliveryFanoutResult()
    dispatcher = SimpleNamespace(deliver_final_response=AsyncMock(return_value=delivered))
    coordinator = ChatExecutionCoordinator(
        tool_registry=ToolRegistry(),
        fact_classifier=ChatFactClassifier(),
        handler_registry=ExecutionHandlerRegistry(),
        agent_run_handler=handler,
        delivery_dispatcher=dispatcher,
    )
    context = SimpleNamespace(session_id="session-1", session_run_id="run-1")
    request = SimpleNamespace(mode=None, context=context)

    assert await coordinator.execute_request(request) is outcome
    handler.execute.assert_awaited_once_with(request)
    dispatcher.deliver_final_response.assert_not_awaited()

    content = DeliveryContent(text=outcome.response_text, turn_id="turn-1", message_id="message-1")
    assert await coordinator.deliver_final_chat_response(context, content=content) is delivered
    dispatcher.deliver_final_response.assert_awaited_once()
    call = dispatcher.deliver_final_response.await_args
    assert call.args[0].context is context
    assert call.kwargs == {
        "response_text": "final answer",
        "attachments": content.attachments,
        "content": content,
        "exclude_chat_sse": False,
    }
