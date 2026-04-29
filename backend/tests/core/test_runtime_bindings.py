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


def test_require_unified_memory_binding_raises_when_unbound() -> None:
    from magi.core.runtime_bindings import require_unified_memory

    with pytest.raises(RuntimeError, match="unified_memory"):
        require_unified_memory()


def test_require_hybrid_retrieval_service_binding_raises_when_unbound() -> None:
    from magi.core.runtime_bindings import require_hybrid_retrieval_service

    with pytest.raises(RuntimeError, match="hybrid_retrieval_service"):
        require_hybrid_retrieval_service()


def test_require_hybrid_retrieval_service_binding_returns_bound_object() -> None:
    from magi.core.runtime_bindings import require_hybrid_retrieval_service

    from dependency_injector import providers

    container = get_container()
    token = object()
    container.hybrid_retrieval_service.override(providers.Object(token))
    try:
        assert require_hybrid_retrieval_service() is token
    finally:
        container.hybrid_retrieval_service.reset_override()
