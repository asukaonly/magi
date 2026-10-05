from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.runtime_trace.provider import resolve_runtime_trace_store


def test_trace_store_resolution_tracks_container_binding_lifecycle():
    provider = get_container().runtime_trace_store
    with provider.override(providers.Object(None)):
        with pytest.raises(RuntimeError, match="runtime_trace_store"):
            resolve_runtime_trace_store()
        first, second = object(), object()
        with provider.override(providers.Object(first)):
            assert resolve_runtime_trace_store() is first
            with provider.override(providers.Object(second)):
                assert resolve_runtime_trace_store() is second
            assert resolve_runtime_trace_store() is first
        with pytest.raises(RuntimeError, match="runtime_trace_store"):
            resolve_runtime_trace_store()
