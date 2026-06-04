from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.core.container import get_container
from magi.plugins.provider import resolve_plugin_manager, resolve_sensor_registry


def test_resolve_plugin_manager_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="plugin_manager"):
        resolve_plugin_manager()


def test_resolve_plugin_manager_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.plugin_manager.override(providers.Object(token))
    try:
        assert resolve_plugin_manager() is token
    finally:
        container.plugin_manager.reset_override()


def test_resolve_sensor_registry_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.sensor_registry.override(providers.Object(token))
    try:
        assert resolve_sensor_registry() is token
    finally:
        container.sensor_registry.reset_override()
