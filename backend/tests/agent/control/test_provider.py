from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.agent.control.provider import (
    resolve_control_session_store,
    resolve_control_settings_manager,
)
from magi.core.container import get_container


def test_resolve_control_session_store_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="control_session_store"):
        resolve_control_session_store()


def test_resolve_control_session_store_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.control_session_store.override(providers.Object(token))
    try:
        assert resolve_control_session_store() is token
    finally:
        container.control_session_store.reset_override()


def test_resolve_control_settings_manager_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.control_settings_manager.override(providers.Object(token))
    try:
        assert resolve_control_settings_manager() is token
    finally:
        container.control_settings_manager.reset_override()
