"""Tests for ChatTaskAgent wiring channel delivery into ChatExecutionCoordinator.

A delivery-dispatcher resolver injection point lets tests pass a stub without
depending on the runtime container.
"""

from __future__ import annotations

import inspect

import pytest

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


def test_chat_task_agent_passes_delivery_dispatcher_to_coordinator() -> None:
    stub = object()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        delivery_dispatcher_resolver=lambda: stub,
    )

    coord = agent._coordinator
    assert coord._delivery_dispatcher is stub
    assert agent._postprocess_service._deliver_final_response is not None


def test_chat_task_agent_wires_delivery_seam_without_private_mutation() -> None:
    init_source = inspect.getsource(ChatTaskAgent.__init__)
    callbacks_source = inspect.getsource(ChatTaskAgent._build_runtime_callbacks)

    assert "_postprocess_service._deliver_final_response" not in init_source
    assert "_build_runtime_callbacks()" in init_source
    assert "deliver_final_response=" in callbacks_source


def test_chat_task_agent_handles_missing_runtime_container() -> None:
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        delivery_dispatcher_resolver=lambda: None,
    )
    assert agent._coordinator._delivery_dispatcher is None
    assert agent._postprocess_service._deliver_final_response is None


def test_chat_task_agent_default_resolver_no_container_does_not_crash() -> None:
    """Without an explicit resolver, ``ChatTaskAgent`` must still construct
    cleanly when the container isn't initialized (test/early-bootstrap paths)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # In tests the runtime_bootstrap_context provider returns a bare ``object``
    # placeholder, so the helper must return None — not crash.
    assert agent._coordinator._delivery_dispatcher is None
    assert agent._postprocess_service._deliver_final_response is None


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
