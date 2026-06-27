from __future__ import annotations

import pytest

from magi.core.container import get_container


def test_require_agent_runtime_binding_returns_bound_object() -> None:
    from magi.core.runtime_bindings import require_agent_runtime

    from dependency_injector import providers

    container = get_container()
    token = object()
    container.agent_runtime.override(providers.Object(token))
    try:
        assert require_agent_runtime() is token
    finally:
        container.agent_runtime.reset_override()


@pytest.mark.asyncio
async def test_chat_message_notifier_binding_defaults_to_noop() -> None:
    from magi.core.runtime_bindings import get_chat_message_notifier

    container = get_container()
    container.chat_message_notifier.reset_override()

    notifier = get_chat_message_notifier()

    await notifier.broadcast_chat_message_upsert(
        user_id="u1",
        session_id="s1",
        message_id="m1",
    )
    await notifier.broadcast_chat_message_hidden(
        user_id="u1",
        session_id="s1",
        message_id="m1",
    )


def test_chat_message_notifier_binding_returns_bound_object() -> None:
    from magi.core.runtime_bindings import get_chat_message_notifier

    from dependency_injector import providers

    container = get_container()
    token = object()
    container.chat_message_notifier.override(providers.Object(token))
    try:
        assert get_chat_message_notifier() is token
    finally:
        container.chat_message_notifier.reset_override()
