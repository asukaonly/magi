from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.plugins.provider import (
    resolve_plugin_manager,
    resolve_plugin_projection_service,
    resolve_source_registry,
)


@pytest.mark.parametrize(
    ("name", "resolve"),
    [
        ("plugin_manager", resolve_plugin_manager),
        ("plugin_projection_service", resolve_plugin_projection_service),
        ("source_registry", resolve_source_registry),
    ],
)
def test_plugin_service_binding_resolves_only_while_bound(name, resolve):
    provider = getattr(get_container(), name)
    token = object()
    with provider.override(providers.Object(None)):
        with pytest.raises(RuntimeError, match=name):
            resolve()
        with provider.override(providers.Object(token)):
            assert resolve() is token
        with pytest.raises(RuntimeError, match=name):
            resolve()
