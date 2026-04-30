from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.agent.background.provider import resolve_background_task_manager
from magi.core.container import get_container


def test_resolve_background_task_manager_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="background_task_manager"):
        resolve_background_task_manager()


def test_resolve_background_task_manager_returns_bound_object() -> None:
    container = get_container()
    token = object()
    container.background_task_manager.override(providers.Object(token))
    try:
        assert resolve_background_task_manager() is token
    finally:
        container.background_task_manager.reset_override()
