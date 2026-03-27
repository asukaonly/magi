"""Tests for process-role bootstrap ownership."""

from __future__ import annotations

import pytest


def test_resolve_process_role_defaults_to_api_mode() -> None:
    """Verify role resolution defaults transport startup to the API role."""
    from magi.process_roles import ProcessRole, resolve_process_role

    assert resolve_process_role(None, env={}) is ProcessRole.API
    assert resolve_process_role("", env={}) is ProcessRole.API


def test_resolve_process_role_rejects_unknown_values() -> None:
    """Verify unsupported process roles fail fast."""
    from magi.process_roles import resolve_process_role

    with pytest.raises(ValueError, match="Unsupported process role"):
        resolve_process_role("worker-bee", env={})


def test_api_role_omits_background_runtime_modules() -> None:
    """Verify API role skips background runtime ownership."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.process_roles import ProcessRole

    modules = build_runtime_modules(RuntimeBootstrapContext(), role=ProcessRole.API)
    module_names = [module.name for module in modules]
    module_by_name = {module.name: module for module in modules}

    assert "runtime_agent_core" not in module_names
    assert "runtime_scheduler" not in module_names
    assert "runtime_agent_scheduler" not in module_names
    assert "runtime_action_scheduler" not in module_names
    assert "runtime_timeline_scheduler" not in module_names
    assert "runtime_tools" not in module_names
    assert "runtime_personality" not in module_names
    assert "runtime_sensor_hub" not in module_names
    assert "runtime_chat_store" in module_names
    assert "runtime_chat_store" in module_by_name["runtime_api_exports"].dependencies
    assert "runtime_message_bus" not in module_by_name["runtime_api_exports"].dependencies
    assert "runtime_personality" not in module_by_name["runtime_api_exports"].dependencies
    assert getattr(module_by_name["runtime_memory"], "start_memory_integration") is False


def test_runtime_worker_role_keeps_background_runtime_modules() -> None:
    """Verify runtime-worker role owns the background runtime graph."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.process_roles import ProcessRole

    modules = build_runtime_modules(RuntimeBootstrapContext(), role=ProcessRole.RUNTIME_WORKER)
    module_names = [module.name for module in modules]
    module_by_name = {module.name: module for module in modules}

    assert "runtime_agent_core" in module_names
    assert "runtime_scheduler" in module_names
    assert "runtime_agent_scheduler" in module_names
    assert "runtime_action_scheduler" in module_names
    assert "runtime_timeline_scheduler" in module_names
    assert "runtime_plugin_ingress_processor" in module_names
    assert "runtime_chat_store" in module_names
    assert "runtime_chat_store" in module_by_name["runtime_exports"].dependencies
    assert getattr(module_by_name["runtime_memory"], "start_memory_integration") is True
