from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from magi.agent.task_agents.handlers import (
    ChatRuntimeContext,
    CapabilitySelection,
    GenericFactPayload,
    IncomingFactKind,
    TurnAdmissionDecision,
)
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.context.contracts import PromptPackage


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False
    provider_name = "openai"

    async def chat(self, **kwargs):
        _ = kwargs
        return "ok"


class TestChatContextOwner(unittest.IsolatedAsyncioTestCase):
    async def test_chat_handlers_delegate_prompt_assembly_to_context_layer(self):
        agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
        agent._context_service.build_prompt_package = AsyncMock(  # type: ignore[attr-defined]
            return_value=PromptPackage(
                prompt_context=None,
                system_prompt="owned-by-context-layer",
                recent_tool_errors_block="",
            )
        )

        context = ChatRuntimeContext(
            latest_fact=None,
            recent_facts=[],
            batch_facts=[],
            agent_id="u-chat",
            agent_type="chat",
            runtime_key="chat:u-chat",
            user_id="u-chat",
            session_id="s-1",
            history_key="u-chat::s-1",
            history=[{"role": "user", "content": "你好"}],
            conversation_history=[{"role": "user", "content": "你好"}],
            recent_tool_errors=[],
            latest_user_message="今天天气怎么样",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        admission = TurnAdmissionDecision(
            run_kind="unified_agent_run",
            execution_mode=None,
            tools=["weather"],
        )
        capabilities = CapabilitySelection(tools=["weather"], reasoning="weather lookup")

        request = await agent.build_execution_request(context, admission, capabilities)

        agent._context_service.build_prompt_package.assert_awaited_once_with(  # type: ignore[attr-defined]
            user_id="u-chat",
            session_id="s-1",
            user_message="今天天气怎么样",
            attachments=[],
            task_category="general",
            tools=["weather"],
            persona_action_tools=[],
            scenario="chat",
            recent_tool_errors=[],
            workspace_path=None,
            persona_id=None,
            allow_implicit_memory=True,
        )
        self.assertEqual(request.system_prompt, "owned-by-context-layer")

    async def test_chat_handlers_add_memory_query_guidance_when_capability_is_selected(self):
        agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
        agent._context_service.build_prompt_package = AsyncMock(  # type: ignore[attr-defined]
            return_value=PromptPackage(
                prompt_context=None,
                system_prompt="owned-by-context-layer",
                recent_tool_errors_block="",
            )
        )

        context = ChatRuntimeContext(
            latest_fact=None,
            recent_facts=[],
            batch_facts=[],
            agent_id="u-chat",
            agent_type="chat",
            runtime_key="chat:u-chat",
            user_id="u-chat",
            session_id="s-1",
            history_key="u-chat::s-1",
            history=[{"role": "user", "content": "昨天我看了什么"}],
            conversation_history=[{"role": "user", "content": "昨天我看了什么"}],
            recent_tool_errors=[],
            latest_user_message="昨天我看了什么",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        admission = TurnAdmissionDecision(
            run_kind="unified_agent_run",
            execution_mode=None,
            tools=["weather", "memory_query"],
        )
        capabilities = CapabilitySelection(
            tools=["weather", "memory_query"],
            reasoning="history lookup",
        )

        request = await agent.build_execution_request(context, admission, capabilities)

        self.assertIn("memory_query", request.selected_tools)
        self.assertIn("source of truth", request.system_prompt.lower())
