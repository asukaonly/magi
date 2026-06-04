from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.runtime_trace.provider import resolve_runtime_trace_store


def test_resolve_runtime_trace_store_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="runtime_trace_store"):
        resolve_runtime_trace_store()


def test_resolve_runtime_trace_store_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.runtime_trace_store.override(providers.Object(token))
    try:
        assert resolve_runtime_trace_store() is token
    finally:
        container.runtime_trace_store.reset_override()
