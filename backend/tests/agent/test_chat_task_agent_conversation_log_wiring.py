"""ChatTaskAgent threads ConversationLog into the two legitimate consumers
(the chat execution coordinator and the session-run coordinator) and tolerates
a missing log when the runtime container is not initialized.

Originally Phase F also routed the log into ``ChatContextAssembler`` so a
dual-write could mirror the cache mutations into the typed event log; that
path was PAUSED (ConversationLog collided with ChatOutcomeWriter writing
to the same chat_messages table, producing duplicate UI rows) and the
audit that followed concluded ConversationLog is in fact a
retract-business store, not a generic conversation history API. The
dual-write fields and the tests covering them were removed; the
remaining wiring covered here is the part that is actually in use.
"""
from __future__ import annotations

from magi.chat.task_agent.chat_task_agent import ChatTaskAgent


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


def test_chat_task_agent_passes_conversation_log_to_coordinator() -> None:
    """Phase F Task 10: the coordinator receives the log so it can
    call ``record_consumed`` per turn."""
    stub = _StubConversationLog()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        delivery_dispatcher_resolver=lambda: None,
        conversation_log_resolver=lambda: stub,
    )
    assert agent._coordinator._conversation_log is stub


def test_chat_task_agent_passes_conversation_log_to_session_run_coordinator() -> None:
    """Phase F Task 11: SessionRunCoordinator receives the log so
    ``request_message_retract`` can append redaction events + find
    dependent runs."""
    stub = _StubConversationLog()
    agent = ChatTaskAgent(
        agent_id="u-chat",
        llm_adapter=_FakeLLMAdapter(),
        delivery_dispatcher_resolver=lambda: None,
        conversation_log_resolver=lambda: stub,
    )
    assert agent._session_run_coordinator._conversation_log is stub


def test_chat_task_agent_default_resolver_no_container_does_not_crash() -> None:
    """Without an explicit resolver, ChatTaskAgent must still construct
    cleanly when the container isn't initialized (test/early-bootstrap paths).

    The downstream coordinators still receive whatever the resolver returned
    (None for the bare-object placeholder used in tests); they tolerate this
    and degrade gracefully.
    """
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    assert agent._coordinator._conversation_log is None
    assert agent._session_run_coordinator._conversation_log is None
