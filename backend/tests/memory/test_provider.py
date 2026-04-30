from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.memory.provider import get_hybrid_retrieval_service, get_unified_memory


def test_get_unified_memory_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="unified_memory"):
        get_unified_memory()


def test_get_hybrid_retrieval_service_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="hybrid_retrieval_service"):
        get_hybrid_retrieval_service()


def test_get_hybrid_retrieval_service_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.hybrid_retrieval_service.override(providers.Object(token))
    try:
        assert get_hybrid_retrieval_service() is token
    finally:
        container.hybrid_retrieval_service.reset_override()
