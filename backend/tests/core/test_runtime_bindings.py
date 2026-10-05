from __future__ import annotations

import pytest

from magi.core.container import get_container


def test_get_optional_agent_runtime_returns_none_when_unbound() -> None:
    from magi.core.runtime_bindings import get_optional_agent_runtime

    container = get_container()
    container.agent_runtime.reset_override()

    assert get_optional_agent_runtime() is None


def test_get_optional_agent_runtime_returns_bound_object_and_propagates_provider_errors() -> None:
    from magi.core.runtime_bindings import get_optional_agent_runtime, require_agent_runtime

    from dependency_injector import providers

    container = get_container()
    token = object()
    container.agent_runtime.override(providers.Object(token))
    try:
        assert get_optional_agent_runtime() is token
        assert require_agent_runtime() is token
    finally:
        container.agent_runtime.reset_override()

    def fail_provider():
        raise ValueError("provider failed")

    container.agent_runtime.override(providers.Callable(fail_provider))
    try:
        with pytest.raises(ValueError, match="provider failed"):
            get_optional_agent_runtime()
        with pytest.raises(ValueError, match="provider failed"):
            require_agent_runtime()
    finally:
        container.agent_runtime.reset_override()

    assert get_optional_agent_runtime() is None
    with pytest.raises(RuntimeError, match="binding is not initialized"):
        require_agent_runtime()


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [False, True])
async def test_chat_writes_persist_with_optional_notification_binding(
    runtime_paths_with_schema, monkeypatch, bound
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from dependency_injector import providers
    from magi.chat import ChatStore
    from magi.chat.surface_writes import ChatSurfaceWriteService
    from magi.core.runtime_bindings import get_chat_message_notifier

    store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    monkeypatch.setattr("magi.chat.surface_writes.get_chat_store", lambda: store)
    notifier = SimpleNamespace(
        broadcast_chat_message_upsert=AsyncMock(), broadcast_chat_message_hidden=AsyncMock()
    )
    provider = get_container().chat_message_notifier
    with provider.override(providers.Object(None)):
        fallback = get_chat_message_notifier()
        with provider.override(providers.Object(notifier if bound else None)):
            if bound:
                assert get_chat_message_notifier() is notifier
            else:
                assert get_chat_message_notifier() is fallback
            service = ChatSurfaceWriteService()
            message_id = await service.append_command_invocation(
                user_id="u1",
                session_id="s1",
                turn_id="t1",
                tool_name="inspect",
                arguments={},
                invocation_text="/inspect",
            )
            record = await store.get_message(message_id)
            assert record.content_text == "/inspect" and record.is_visible
            assert await service.hide_message(user_id="u1", session_id="s1", message_id=message_id)
            assert not (await store.get_message(message_id)).is_visible
            if bound:
                notifier.broadcast_chat_message_upsert.assert_awaited_once_with(
                    user_id="u1", session_id="s1", message_id=message_id
                )
                notifier.broadcast_chat_message_hidden.assert_awaited_once_with(
                    user_id="u1", session_id="s1", message_id=message_id
                )
            else:
                notifier.broadcast_chat_message_upsert.assert_not_awaited()
                notifier.broadcast_chat_message_hidden.assert_not_awaited()
        assert get_chat_message_notifier() is fallback
    await store.shutdown()
