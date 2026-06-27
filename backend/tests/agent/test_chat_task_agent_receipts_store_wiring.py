"""Tests for ChatTaskAgent threading delivery dispatch into run coordination.

ChatTaskAgent must pass the channel-owned dispatcher into
``SessionRunCoordinator`` so retract can undo previously delivered messages
without chat knowing the channel router or receipts store details.
"""
from __future__ import annotations

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


def test_chat_task_agent_passes_delivery_dispatcher_to_session_coordinator() -> None:
    stub = object()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        delivery_dispatcher_resolver=lambda: stub,
    )
    assert agent._session_run_coordinator._delivery_dispatcher is stub


def test_chat_task_agent_handles_missing_delivery_dispatcher() -> None:
    """Default resolver returns None when container not initialized."""
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        delivery_dispatcher_resolver=lambda: None,
    )
    assert agent._session_run_coordinator._delivery_dispatcher is None


def test_chat_task_agent_default_resolver_no_container_does_not_crash() -> None:
    """Without an explicit resolver, ``ChatTaskAgent`` must still construct
    cleanly when the container isn't initialized (test/early-bootstrap paths)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # In tests the runtime_bootstrap_context provider returns a bare ``object``
    # placeholder, so the helper must return None — not crash.
    assert agent._session_run_coordinator._delivery_dispatcher is None
