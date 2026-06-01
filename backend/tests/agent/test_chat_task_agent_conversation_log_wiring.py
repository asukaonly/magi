"""ChatTaskAgent threads ConversationLog into ChatHistoryService (Phase F, Task 7).

Mirrors the shape of ``test_chat_task_agent_receipts_store_wiring.py``: the
agent exposes a ``conversation_log_resolver`` kwarg, falls back to a static
helper that reads the runtime container, and forwards the resolved log into
``ChatHistoryService`` so future Task 8 wiring can consume typed events.
"""
from __future__ import annotations

from magi.agent.task_agents.chat_task_agent import ChatTaskAgent


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


class _StubConversationLog:
    async def append(self, ev, *, session_id):
        return None

    async def materialize(self, **kw):
        return []

    async def find_dependents(self, **kw):
        return []

    async def record_consumed(self, **kw):
        return None


def test_chat_task_agent_passes_conversation_log_to_history_service() -> None:
    stub = _StubConversationLog()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
        receipts_store_resolver=lambda: None,
        conversation_log_resolver=lambda: stub,
    )
    assert agent._history_service._conversation_log is stub


def test_chat_task_agent_handles_missing_conversation_log() -> None:
    """Default resolver returns None when container unavailable."""
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        channel_registry_resolver=lambda: None,
        receipts_store_resolver=lambda: None,
        conversation_log_resolver=lambda: None,
    )
    assert agent._history_service._conversation_log is None


def test_chat_task_agent_default_resolver_no_container_does_not_crash() -> None:
    """Without an explicit resolver, ChatTaskAgent must still construct
    cleanly when the container isn't initialized (test/early-bootstrap paths)."""
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    # In tests the runtime_bootstrap_context provider returns a bare ``object``
    # placeholder, so the helper must return None — not crash.
    assert agent._history_service._conversation_log is None
