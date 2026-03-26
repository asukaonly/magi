from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from magi.agent.task_agents.chat import (
    ChatRuntimeContext,
    ExecutionMode,
    GenericFactPayload,
    IncomingFactKind,
    IntentDecision,
    OrchestrationPlan,
    ToolSelection,
)
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
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
            active_orchestrations=[],
            recent_tool_errors=[],
            latest_user_message="今天天气怎么样",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        intent_result = IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.FUNCTION_CALLING,
            tools=["weather"],
            orchestration_plan=OrchestrationPlan(),
        )
        tool_result = ToolSelection(tools=["weather"], reasoning="weather lookup")

        llm_params = await agent.assemble_llm_params(context, intent_result, tool_result)

        agent._context_service.build_prompt_package.assert_awaited_once_with(  # type: ignore[attr-defined]
            user_id="u-chat",
            session_id="s-1",
            user_message="今天天气怎么样",
            attachments=[],
            task_category="chat",
            tools=["weather"],
            scenario="chat",
            recent_tool_errors=[],
            workspace_path=None,
        )
        self.assertEqual(llm_params.system_prompt, "owned-by-context-layer")

    async def test_chat_handlers_add_memory_query_guidance_for_explicit_memory_route(self):
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
            active_orchestrations=[],
            recent_tool_errors=[],
            latest_user_message="昨天我看了什么",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=GenericFactPayload(),
        )
        intent_result = IntentDecision(
            intent="chat",
            difficulty="normal",
            execution_mode=ExecutionMode.FUNCTION_CALLING,
            tools=["weather", "memory_query"],
            orchestration_plan=OrchestrationPlan(),
            memory_route="explicit_query",
            routing_memory_hint={
                "query": "昨天我看了什么",
                "query_mode": "detail",
                "sources": ["timeline"],
                "time_range": {"relative": "1d"},
            },
        )
        tool_result = ToolSelection(tools=["weather", "memory_query"], reasoning="history lookup")

        llm_params = await agent.assemble_llm_params(context, intent_result, tool_result)

        self.assertEqual(llm_params.selected_tools[0], "memory_query")
        self.assertIn("Use `memory_query` before answering", llm_params.system_prompt)
        self.assertIn('"sources": ["timeline"]', llm_params.system_prompt)
