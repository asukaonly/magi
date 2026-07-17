"""Tests for process-role bootstrap ownership."""

from __future__ import annotations


def test_process_role_constants_exist() -> None:
    """Verify process role module exports expected constants."""
    from magi.bootstrap.process_roles import PROCESS_ROLE_ENV_VAR, PROCESS_ROLE_VALUE

    assert PROCESS_ROLE_ENV_VAR == "MAGI_PROCESS_ROLE"
    assert PROCESS_ROLE_VALUE == "ipc_worker"


def test_build_runtime_modules_includes_full_runtime() -> None:
    """Verify IPC worker builds the full runtime module graph."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    modules = build_runtime_modules(RuntimeBootstrapContext())
    module_names = [module.name for module in modules]
    module_by_name = {module.name: module for module in modules}

    assert "runtime_agent_core" in module_names
    assert "runtime_scheduler" in module_names
    assert "runtime_sensor_scheduler" in module_names
    assert "runtime_sensor_sync_executor" in module_names
    assert "runtime_l1_maintenance_scheduler" in module_names
    assert "runtime_l2_maintenance_scheduler" in module_names
    assert "runtime_l2_consolidation_scheduler" in module_names
    assert "runtime_l3_summary_scheduler" in module_names
    assert "runtime_l3_maintenance_scheduler" in module_names
    assert "runtime_plugin_ingress_processor" in module_names
    assert "runtime_chat_store" in module_names
    assert "runtime_chat_forgetting_recovery" in module_names
    assert {
        "runtime_chat_store",
        "runtime_memory",
    } <= set(module_by_name["runtime_chat_forgetting_recovery"].dependencies)
    assert "runtime_chat_store" in module_by_name["runtime_exports"].dependencies
    assert getattr(module_by_name["runtime_memory"], "start_memory_integration") is True
