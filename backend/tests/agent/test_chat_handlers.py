from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.agent.cancel import NullCancelToken
from magi.agent.task_agents.chat.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.chat import direct_handler as direct_handler_module
from magi.agent.task_agents.chat.direct_handler import DirectLLMHandler
from magi.agent.task_agents.chat.handlers import FunctionCallingHandler
from magi.agent.task_agents.common import DirectLLMRequest, ExecutionMode, IncomingFactKind, OrchestrationPlan, ToolSelection, UserMessagePayload


class _FakeContextService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def build_prompt_package(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return SimpleNamespace(prompt_context={}, system_prompt="sys")


class _FakePromptService:
    def __init__(self) -> None:
        self.call_llm_calls = 0

    def augment_system_prompt_with_reply_context(
        self,
        *,
        system_prompt,
        reply_context=None,
        recent_tool_state=None,
    ):
        _ = (reply_context, recent_tool_state)
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
        self.call_llm_calls += 1
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
    handler = DirectLLMHandler(SimpleNamespace(prompt_service=_FakePromptService()))
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
async def test_direct_llm_handler_passes_stored_persona_id_into_context_service() -> None:
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
        latest_user_message="hello",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="hello",
            turn_id="turn-1",
        ),
        active_persona_id="persona-turn",
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

    assert context_service.calls[0]["persona_id"] == "persona-turn"
    assert context_service.calls[0]["scenario"] == "chat"
    assert context_service.calls[0]["task_category"] == "chat"
    assert context_service.calls[0]["tools"] == []


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
async def test_function_calling_handler_passes_stored_persona_id_into_context_service() -> None:
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
            turn_id="turn-1",
        ),
        active_persona_id="persona-tool-turn",
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
            ),
            tool_selection=ToolSelection(tools=["glob"], reasoning="search repo"),
        )
    )

    assert context_service.calls[0]["persona_id"] == "persona-tool-turn"
    assert context_service.calls[0]["scenario"] == "chat"
    assert context_service.calls[0]["task_category"] == "chat"
    assert context_service.calls[0]["tools"] == ["glob"]


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
            ),
            tool_selection=ToolSelection(tools=["glob"], reasoning="search repo"),
        )
    )

    assert context_service.calls[0]["workspace_path"] == "/tmp/turn-workspace"


@pytest.mark.asyncio
async def test_function_calling_handler_appends_scope_guidance_from_task_hint() -> None:
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
        latest_user_message="详细对比下 Magi 和 AnotherProject 的记忆实现",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="详细对比下 Magi 和 AnotherProject 的记忆实现",
            turn_id="turn-1",
        ),
    )

    request = await handler.build_request(
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
                task_hint={
                    "target_locality": "ambiguous_external_reference",
                    "preferred_resolution_order": "ask_or_web_before_external_scan",
                    "requires_clarification": True,
                },
            ),
            tool_selection=ToolSelection(tools=["web-search", "file_read"], reasoning="compare", task_hint={}),
        )
    )

    assert "# Scope Guidance" in request.system_prompt
    assert "ask the user for a path or use web-search before any external local scan" in request.system_prompt


@pytest.mark.asyncio
async def test_function_calling_handler_adds_photo_workflow_guidance_when_photo_tools_selected() -> None:
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
        latest_user_message="把刚才那些照片发出来",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="把刚才那些照片发出来",
            turn_id="turn-1",
        ),
    )

    request = await handler.build_request(
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
            ),
            tool_selection=ToolSelection(
                tools=["photo_library_resolve_photo_refs", "prepare_chat_attachments"],
                reasoning="send previous photo candidates",
            ),
        )
    )

    assert "# Attachment Preparation Guidance" in request.system_prompt
    assert "source resolver tool" in request.system_prompt
    assert "prepare_chat_attachments" in request.system_prompt
    assert "structured message metadata" in request.system_prompt
    assert "Do not emit attachment JSON" in request.system_prompt


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
        core_model_supports_vision=True,
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


@pytest.mark.asyncio
async def test_direct_llm_handler_returns_clear_message_when_image_model_lacks_vision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct_handler_module, "get_user_preference", lambda key, default=None: "en")
    image_path = tmp_path / "diagram.png"
    image_path.write_bytes(b"fake-image-bytes")

    prompt_service = _FakePromptService()
    handler = DirectLLMHandler(
        SimpleNamespace(
            context_service=_FakeContextService(),
            prompt_service=prompt_service,
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
        core_model_supports_vision=False,
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
    result = await handler.execute(request)

    assert "does not support image input" in result.response_text
    assert prompt_service.call_llm_calls == 0
    assert request.messages[0]["content"] == "describe this screenshot"


@pytest.mark.asyncio
async def test_direct_llm_handler_localizes_image_model_lacks_vision_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct_handler_module, "get_user_preference", lambda key, default=None: "zh")
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
        latest_user_message="描述这张图",
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        core_model_supports_vision=False,
        latest_payload=UserMessagePayload(
            user_id="local_user",
            session_id="session-1",
            content="描述这张图",
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
    result = await handler.execute(request)

    assert "当前核心模型不支持图片输入" in result.response_text


class _FakeCoordinator:
    """Minimal coordinator stub for ``_build_cancel_token`` tests.

    Returns the configured status only when the queried ``(session_id, run_id,
    revision)`` triple matches; returns ``None`` otherwise, mirroring the real
    :meth:`SessionRunCoordinator.get_run_status` contract.
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        revision: int | None = None,
        status: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.run_id = run_id
        self.revision = revision
        self.status = status
        self.calls: list[dict[str, object]] = []

    def get_run_status(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> str | None:
        self.calls.append(
            {"session_id": session_id, "run_id": run_id, "revision": revision}
        )
        if self.session_id is not None and session_id != self.session_id:
            return None
        if run_id is not None and self.run_id is not None and run_id != self.run_id:
            return None
        if revision is not None and self.revision is not None and int(revision) != int(self.revision):
            return None
        return self.status


def _make_cancel_request(
    *,
    session_id: str | None = "session-1",
    session_run_id: str | None = "run-1",
    session_run_revision: int | None = 0,
) -> object:
    return SimpleNamespace(
        context=SimpleNamespace(
            session_id=session_id,
            session_run_id=session_run_id,
            session_run_revision=session_run_revision,
        )
    )


def test_build_cancel_token_returns_noop_when_no_coordinator() -> None:
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=None))

    token = handler._build_cancel_token(_make_cancel_request())

    assert isinstance(token, NullCancelToken)


def test_build_cancel_token_returns_noop_when_session_id_missing() -> None:
    coordinator = _FakeCoordinator()
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request(session_id=""))

    assert isinstance(token, NullCancelToken)


def test_build_cancel_token_returns_noop_when_run_id_missing() -> None:
    coordinator = _FakeCoordinator()
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request(session_run_id=None))

    assert isinstance(token, NullCancelToken)


@pytest.mark.asyncio
async def test_build_cancel_token_false_when_run_is_running() -> None:
    coordinator = _FakeCoordinator(
        session_id="session-1", run_id="run-1", revision=0, status="running"
    )
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request())

    assert not isinstance(token, NullCancelToken)
    assert await token.is_cancelled() is False
    assert coordinator.calls[-1] == {
        "session_id": "session-1",
        "run_id": "run-1",
        "revision": 0,
    }


@pytest.mark.asyncio
async def test_build_cancel_token_true_when_run_is_cancelling() -> None:
    coordinator = _FakeCoordinator(
        session_id="session-1", run_id="run-1", revision=0, status="cancelling"
    )
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request())

    assert await token.is_cancelled() is True
    assert token.reason == "session_run_cancelling"


@pytest.mark.asyncio
async def test_build_cancel_token_true_when_run_is_cancelled() -> None:
    coordinator = _FakeCoordinator(
        session_id="session-1", run_id="run-1", revision=0, status="cancelled"
    )
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request())

    assert await token.is_cancelled() is True
    assert token.reason == "session_run_cancelled"


@pytest.mark.asyncio
async def test_build_cancel_token_false_when_revision_has_advanced() -> None:
    """A superseded revision must not appear cancelled to the old tool-loop.

    After an INTERRUPT, :meth:`SessionRunCoordinator.bump_revision` advances
    the run revision without marking the old revision as ``cancelling``. The
    cancel token was bound to the old revision and must therefore stay
    ``False`` — the superseded loop completes naturally and its result is
    later filtered out by :meth:`SessionRunCoordinator.record_result`.
    """
    coordinator = _FakeCoordinator(
        session_id="session-1", run_id="run-1", revision=1, status="running"
    )
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(
        _make_cancel_request(session_run_revision=0)
    )

    assert await token.is_cancelled() is False


@pytest.mark.asyncio
async def test_build_cancel_token_false_when_run_id_has_changed() -> None:
    """A new run has replaced the one the token was bound to."""
    coordinator = _FakeCoordinator(
        session_id="session-1", run_id="run-2", revision=0, status="cancelling"
    )
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request())

    assert await token.is_cancelled() is False


@pytest.mark.asyncio
async def test_build_cancel_token_false_when_active_run_cleared() -> None:
    """``get_run_status`` returns ``None`` once the active run is completed."""
    coordinator = _FakeCoordinator(status=None)
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request())

    assert await token.is_cancelled() is False


@pytest.mark.asyncio
async def test_build_cancel_token_reflects_state_transitions_on_each_call() -> None:
    """The token polls the coordinator live; no status is cached."""
    coordinator = _FakeCoordinator(
        session_id="session-1", run_id="run-1", revision=0, status="running"
    )
    handler = FunctionCallingHandler(SimpleNamespace(session_run_coordinator=coordinator))

    token = handler._build_cancel_token(_make_cancel_request())

    assert await token.is_cancelled() is False
    coordinator.status = "cancelling"
    assert await token.is_cancelled() is True
    coordinator.status = "cancelled"
    assert await token.is_cancelled() is True
    coordinator.status = None
    assert await token.is_cancelled() is False

