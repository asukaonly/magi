from __future__ import annotations

from dependency_injector import providers
import pytest

from magi.core.container import get_container


def test_require_other_memory_binding_raises_when_unbound() -> None:
    from magi.core.runtime_bindings import require_other_memory

    with pytest.raises(RuntimeError, match="other_memory"):
        require_other_memory()


def test_require_message_bus_binding_returns_bound_object() -> None:
    from magi.core.runtime_bindings import require_message_bus

    container = get_container()
    token = object()
    container.message_bus.override(providers.Object(token))
    try:
        assert require_message_bus() is token
    finally:
        container.message_bus.reset_override()
