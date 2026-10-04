"""Tests for ChatTaskAgent wiring channel delivery into ChatExecutionCoordinator.

A delivery-dispatcher resolver injection point lets tests pass a stub without
depending on the runtime container.
"""

from __future__ import annotations


import pytest

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


@pytest.mark.parametrize("binding", ["injected", "explicit_none", "default"])
def test_chat_assembly_shares_dependencies_between_both_coordinators(binding):
    from unittest.mock import Mock

    dispatcher = object() if binding == "injected" else None
    conversation_log = object() if binding == "injected" else None
    shared_skill_runner = object()
    delivery_resolver = Mock(return_value=dispatcher)
    log_resolver = Mock(return_value=conversation_log)
    dependencies = (
        {}
        if binding == "default"
        else {
            "delivery_dispatcher_resolver": delivery_resolver,
            "conversation_log_resolver": log_resolver,
        }
    )
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        skill_runner=shared_skill_runner,
        **dependencies
    )
    for coordinator in (agent._coordinator, agent._session_run_coordinator):
        assert coordinator._delivery_dispatcher is dispatcher
        assert coordinator._conversation_log is conversation_log
    assert agent.function_calling_orchestrator.skill_runner is shared_skill_runner
    callback = agent._postprocess_service._deliver_final_response
    if dispatcher is None:
        assert callback is None
    else:
        assert callback == agent._deliver_final_response_from_postprocess
    if binding != "default":
        delivery_resolver.assert_called_once_with()
        log_resolver.assert_called_once_with()


@pytest.mark.asyncio
async def test_chat_task_agent_forwards_streamed_delivery_filter() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    calls: list[dict] = []

    class _Coordinator:
        async def deliver_final_chat_response(
            self,
            context,
            *,
            content,
            exclude_chat_sse=False,
            exclude_channel_types=(),
        ):
            calls.append(
                {
                    "context": context,
                    "content": content,
                    "exclude_chat_sse": exclude_chat_sse,
                    "exclude_channel_types": tuple(exclude_channel_types),
                }
            )
            return ["ok"]

    agent._coordinator = _Coordinator()
    result = await agent._deliver_final_response_from_postprocess(
        "context",
        content="content",
        exclude_chat_sse=True,
        exclude_channel_types={"telegram"},
    )

    assert result == ["ok"]
    assert calls == [
        {
            "context": "context",
            "content": "content",
            "exclude_chat_sse": True,
            "exclude_channel_types": ("telegram",),
        }
    ]
