from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.agent.background.provider import resolve_background_task_manager
from magi.core.container import get_container


def test_background_manager_resolves_only_while_binding_is_available():
    provider = get_container().background_task_manager
    token = object()
    with provider.override(providers.Object(None)):
        with pytest.raises(RuntimeError, match="background_task_manager"):
            resolve_background_task_manager()
        with provider.override(providers.Object(token)):
            assert resolve_background_task_manager() is token
        with pytest.raises(RuntimeError, match="background_task_manager"):
            resolve_background_task_manager()
