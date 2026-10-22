from __future__ import annotations

import pytest

from magi.runtime_trace.chat_trace.read_service import get_chat_trace_read_service
from magi.chat.provider import get_chat_read_service
from magi.core.container import init_container


@pytest.mark.parametrize(
    "provider_name,getter",
    [
        ("chat_trace_read_service", get_chat_trace_read_service),
    ],
)
def test_read_service_binding_shares_one_instance_until_reset(provider_name, getter):
    container = init_container()
    provider = getattr(container, provider_name)
    first = getter()
    try:
        assert getter() is first
        assert provider() is first
        provider.reset()
        second = getter()
        assert second is not first
        assert getter() is second and provider() is second
    finally:
        provider.reset()


def test_chat_reader_requires_explicit_storage_binding():
    init_container()
    with pytest.raises(RuntimeError, match="chat_read_service"):
        get_chat_read_service()
