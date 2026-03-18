from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.task_agents.chat.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.chat.handlers import DirectLLMHandler
from magi.agent.task_agents.common import DirectLLMRequest, ExecutionMode, IncomingFactKind, OrchestrationPlan, ToolSelection, UserMessagePayload


class _FakePromptService:
    async def call_llm(  # type: ignore[no-untyped-def]
        self,
        *,
        system_prompt,
        messages,
        disable_thinking=True,
        json_mode=False,
        timeout_seconds=None,
        llm_trace_callback=None,
    ):
        _ = (system_prompt, messages, disable_thinking, json_mode, timeout_seconds)
        if llm_trace_callback is not None:
            callback_result = llm_trace_callback(
                {
                    "provider": "openai",
                    "model": "gpt-test",
                    "input_tokens": 64,
                    "output_tokens": 18,
                    "total_tokens": 82,
                    "thinking_enabled": False,
                    "duration_ms": 920,
                }
            )
            if hasattr(callback_result, "__await__"):
                await callback_result
        return "final answer"


@pytest.mark.asyncio
async def test_direct_llm_handler_carries_llm_trace_into_execution_result() -> None:
    handler = DirectLLMHandler(SimpleNamespace(prompt_service=_FakePromptService()))
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="web_user",
        agent_type="chat",
        runtime_key="chat:web_user",
        user_id="web_user",
        session_id="session-1",
        history_key="web_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="web_user",
            session_id="session-1",
            message="hello",
            turn_id="turn-1",
        ),
    )
    request = DirectLLMRequest(
        mode=ExecutionMode.DIRECT_LLM,
        context=context,
        intent=IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.DIRECT_LLM,
            reasoning="direct",
            orchestration_plan=OrchestrationPlan(),
        ),
        tool_selection=ToolSelection(tools=[], reasoning="direct"),
        system_prompt="sys",
        messages=[{"role": "user", "content": "hello"}],
        disable_thinking=True,
    )

    result = await handler.execute(request)

    assert result.response_text == "final answer"
    assert result.llm_trace["model"] == "gpt-test"
    assert result.llm_trace["input_tokens"] == 64
    assert result.llm_trace["duration_ms"] == 920
