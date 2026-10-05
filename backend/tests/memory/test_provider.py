from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.memory.provider import get_hybrid_retrieval_service, get_unified_memory


@pytest.mark.parametrize(
    ("name", "resolve"),
    [
        ("unified_memory", get_unified_memory),
        ("hybrid_retrieval_service", get_hybrid_retrieval_service),
    ],
)
def test_memory_services_resolve_only_while_binding_is_available(name, resolve):
    provider = getattr(get_container(), name)
    token = object()
    with provider.override(providers.Object(None)):
        with pytest.raises(RuntimeError, match=name):
            resolve()
        with provider.override(providers.Object(token)):
            assert resolve() is token
        with pytest.raises(RuntimeError, match=name):
            resolve()
