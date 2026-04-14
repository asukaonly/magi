from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.agent.task_agents.chat.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.chat.handlers import DirectLLMHandler, FunctionCallingHandler
from magi.agent.task_agents.common import DirectLLMRequest, ExecutionMode, IncomingFactKind, OrchestrationPlan, ToolSelection, UserMessagePayload


class _FakeContextService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def build_prompt_package(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return SimpleNamespace(prompt_context={}, system_prompt="sys")


class _FakePromptService:
    def augment_system_prompt_with_reply_context(self, *, system_prompt, reply_context=None):
        return system_prompt

    async def call_llm(  # type: ignore[no-untyped-def]
        self,
        *,
        system_prompt,
        messages,
        disable_thinking=True,
        thinking_depth=None,
        json_mode=False,
        timeout_seconds=None,
        llm_trace_callback=None,
    ):
        _ = (system_prompt, messages, disable_thinking, thinking_depth, json_mode, timeout_seconds)
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
    handler = DirectLLMHandler(SimpleNamespace(prompt_service=_FakePromptService(), stream_chunk_callback=None))
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
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
    )

    result = await handler.execute(request)

    assert result.response_text == "final answer"
    assert result.llm_trace["model"] == "gpt-test"
    assert result.llm_trace["input_tokens"] == 64
    assert result.llm_trace["duration_ms"] == 920


@pytest.mark.asyncio
async def test_direct_llm_handler_does_not_duplicate_latest_user_message_from_history() -> None:
    context_service = _FakeContextService()
    handler = DirectLLMHandler(
        SimpleNamespace(
            context_service=context_service,
            prompt_service=_FakePromptService(),
        )
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[{"role": "user", "content": "hello"}],
        conversation_history=[{"role": "user", "content": "hello"}],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
    )

    request = await handler.build_request(
        SimpleNamespace(
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
        )
    )

    assert request.messages == [{"role": "user", "content": "hello"}]
    assert context_service.calls[0]["attachments"] == []


@pytest.mark.asyncio
async def test_direct_llm_handler_passes_uploaded_attachments_into_context_service() -> None:
    context_service = _FakeContextService()
    handler = DirectLLMHandler(
        SimpleNamespace(
            context_service=context_service,
            prompt_service=_FakePromptService(),
        )
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="summarize this file",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="summarize this file",
            attachments=[{"attachment_id": "att-1", "kind": "text_file", "original_name": "notes.md"}],
            turn_id="turn-1",
        ),
    )

    await handler.build_request(
        SimpleNamespace(
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
        )
    )

    assert context_service.calls[0]["attachments"] == [
        {"attachment_id": "att-1", "kind": "text_file", "original_name": "notes.md"}
    ]


@pytest.mark.asyncio
async def test_direct_llm_handler_passes_turn_workspace_into_context_service() -> None:
    context_service = _FakeContextService()
    handler = DirectLLMHandler(
        SimpleNamespace(
            context_service=context_service,
            prompt_service=_FakePromptService(),
        )
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="inspect this repo",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="inspect this repo",
            workspace_path="/tmp/turn-workspace",
            turn_id="turn-1",
        ),
    )

    await handler.build_request(
        SimpleNamespace(
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
        )
    )

    assert context_service.calls[0]["workspace_path"] == "/tmp/turn-workspace"


@pytest.mark.asyncio
async def test_function_calling_handler_passes_turn_workspace_into_context_service() -> None:
    context_service = _FakeContextService()
    handler = FunctionCallingHandler(
        SimpleNamespace(
            context_service=context_service,
            prompt_service=_FakePromptService(),
        )
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="inspect this repo",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="inspect this repo",
            workspace_path="/tmp/turn-workspace",
            turn_id="turn-1",
        ),
    )

    await handler.build_request(
        SimpleNamespace(
            mode=ExecutionMode.FUNCTION_CALLING,
            context=context,
            intent=IntentDecision(
                intent="chat",
                difficulty="normal",
                execution_mode=ExecutionMode.FUNCTION_CALLING,
                reasoning="tool use",
                orchestration_plan=OrchestrationPlan(),
                memory_route="none",
                routing_memory_hint=None,
            ),
            tool_selection=ToolSelection(tools=["glob"], reasoning="search repo"),
        )
    )

    assert context_service.calls[0]["workspace_path"] == "/tmp/turn-workspace"


@pytest.mark.asyncio
async def test_direct_llm_handler_builds_multimodal_message_for_image_attachments(tmp_path: Path) -> None:
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"fake-image-bytes")

    handler = DirectLLMHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=_FakePromptService(),
        )
    )
    context = ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="local_user",
        agent_type="chat",
        runtime_key="chat:local_user",
        user_id="local_user",
        session_id="session-1",
        history_key="local_user::session-1",
        history=[],
        conversation_history=[],
        active_orchestrations=[],
        recent_tool_errors=[],
        latest_user_message="describe this screenshot",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="describe this screenshot",
            attachments=[
                {
                    "attachment_id": "att-image",
                    "kind": "image",
                    "original_name": "diagram.png",
                    "mime_type": "image/png",
                    "storage_path": str(image_path),
                }
            ],
            turn_id="turn-1",
        ),
    )

    request = await handler.build_request(
        SimpleNamespace(
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
        )
    )

    assert request.messages[0]["role"] == "user"
    assert request.messages[0]["content"][0]["type"] == "text"
    assert request.messages[0]["content"][1]["type"] == "image"
    assert request.messages[0]["content"][1]["mime_type"] == "image/png"
