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


def test_get_optional_agent_runtime_returns_none_when_unbound() -> None:
    from magi.core.runtime_bindings import get_optional_agent_runtime

    container = get_container()
    container.agent_runtime.reset_override()

    assert get_optional_agent_runtime() is None


def test_get_optional_agent_runtime_returns_bound_object_and_propagates_provider_errors() -> None:
    from magi.core.runtime_bindings import get_optional_agent_runtime

    from dependency_injector import providers

    container = get_container()
    token = object()
    container.agent_runtime.override(providers.Object(token))
    try:
        assert get_optional_agent_runtime() is token
    finally:
        container.agent_runtime.reset_override()

    def fail_provider():
        raise ValueError("provider failed")

    container.agent_runtime.override(providers.Callable(fail_provider))
    try:
        with pytest.raises(ValueError, match="provider failed"):
            get_optional_agent_runtime()
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
