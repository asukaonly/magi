from __future__ import annotations

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
