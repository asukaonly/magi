"""Tests for ChatTaskAgent wiring the ChannelRegistry into ChatExecutionCoordinator.

Phase G+1 (Task 6): ChatTaskAgent must pull the live ``ChannelRegistry`` out of
the runtime container at construction time and pass it into
``ChatExecutionCoordinator`` so ``DeliveryRouter`` fanout fires in production.
A ``channel_registry_resolver`` injection point is exposed so tests can pass a
stub without depending on the runtime container.
"""
from __future__ import annotations

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.channels.delivery_router import DeliveryRouter


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


class _StubChannelRegistry:
    """Bare-bones registry — DeliveryRouter only needs ``get``/``register``."""

    def get(self, key):  # noqa: D401, ANN001
        return None

    def register(self, channel):  # noqa: D401, ANN001
        return None


def test_chat_task_agent_passes_channel_registry_to_coordinator() -> None:
    """When a registry resolver returns a real registry, the coordinator should
    construct a ``DeliveryRouter`` wrapping it."""
    stub = _StubChannelRegistry()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: stub,
    )

    coord = agent._coordinator
    assert coord._delivery_router is not None
    assert isinstance(coord._delivery_router, DeliveryRouter)
    # The router's internal registry must be exactly the stub we injected
    assert coord._delivery_router._channel_registry is stub


def test_chat_task_agent_handles_missing_runtime_container() -> None:
    """Default resolver returns None when get_container() raises — coordinator
    falls back to no-delivery legacy path without ChatTaskAgent crashing."""
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
    )
    assert agent._coordinator._delivery_router is None


def test_chat_task_agent_default_resolver_no_container_does_not_crash() -> None:
    """Without an explicit resolver, ``ChatTaskAgent`` must still construct
    cleanly when the container isn't initialized (test/early-bootstrap paths)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # In tests the runtime_bootstrap_context provider returns a bare ``object``
    # placeholder, so the helper must return None — not crash.
    assert agent._coordinator._delivery_router is None
