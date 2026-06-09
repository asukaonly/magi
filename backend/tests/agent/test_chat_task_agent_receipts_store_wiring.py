"""Tests for ChatTaskAgent threading DeliveryReceiptsStore into the coordinator.

Phase G+3 (Task 5): ChatTaskAgent must pull the live ``DeliveryReceiptsStore``
out of the runtime container (``ChannelsModule._receipts_store``) at
construction time and pass it into ``ChatExecutionCoordinator`` so the new
receipts-write path fires in production.

A ``receipts_store_resolver`` injection point is exposed so tests can pass a
stub without depending on the runtime container.
"""
from __future__ import annotations

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


class _StubReceiptsStore:
    async def save_receipts(self, **kw):
        return None

    async def list_receipts(self, **kw):
        return []

    async def clear_receipts(self, **kw):
        return None


def test_chat_task_agent_passes_receipts_store_to_coordinator() -> None:
    stub = _StubReceiptsStore()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
        receipts_store_resolver=lambda: stub,
    )
    assert agent._coordinator._receipts_store is stub


def test_chat_task_agent_handles_missing_receipts_store() -> None:
    """Default resolver returns None when container not initialized."""
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
        receipts_store_resolver=lambda: None,
    )
    assert agent._coordinator._receipts_store is None


def test_chat_task_agent_default_resolver_no_container_does_not_crash() -> None:
    """Without an explicit resolver, ``ChatTaskAgent`` must still construct
    cleanly when the container isn't initialized (test/early-bootstrap paths)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # In tests the runtime_bootstrap_context provider returns a bare ``object``
    # placeholder, so the helper must return None — not crash.
    assert agent._coordinator._receipts_store is None
