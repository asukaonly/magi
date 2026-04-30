from __future__ import annotations

from magi.api.services.chat_trace.read_service import get_chat_trace_read_service
from magi.chat.read_service import get_chat_read_service
from magi.core.container import init_container


def test_chat_read_service_getter_uses_container_singleton() -> None:
    container = init_container()

    first = get_chat_read_service()
    second = get_chat_read_service()

    try:
        assert first is second
        assert first is container.chat_read_service()
    finally:
        first.close()
        container.chat_read_service.reset()


def test_chat_trace_read_service_getter_uses_container_singleton() -> None:
    container = init_container()

    first = get_chat_trace_read_service()
    second = get_chat_trace_read_service()

    assert first is second
    assert first is container.chat_trace_read_service()
    container.chat_trace_read_service.reset()