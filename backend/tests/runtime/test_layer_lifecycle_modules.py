"""Tests for layer-owned lifecycle modules and bootstrap context."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_runtime_bootstrap_context_exposes_layer_slices() -> None:
    """Verify RuntimeBootstrapContext exposes expected layer state slices."""
    from magi.bootstrap.context import RuntimeBootstrapContext

    context = RuntimeBootstrapContext()

    assert hasattr(context, "core")
    assert hasattr(context, "llm")
    assert hasattr(context, "memory")
    assert hasattr(context, "agent_runtime")
    assert hasattr(context, "scheduler")


def test_require_initialized_raises_for_missing_value() -> None:
    """Verify require_initialized raises RuntimeError for None values."""
    from magi.bootstrap.context import require_initialized

    with pytest.raises(RuntimeError, match="missing_field is not initialized"):
        require_initialized(None, "missing_field")

    # Verify it returns the value when not None
    assert require_initialized("value", "field") == "value"


def test_infrastructure_and_platform_layers_own_their_lifecycle_modules() -> None:
    """Verify infrastructure layers (config, events, plugins) own their lifecycle modules."""
    from magi.config.lifecycle import ConfigurationModule
    from magi.events.lifecycle import MessageBusModule
    from magi.plugins.lifecycle import PluginSystemModule

    assert ConfigurationModule.__module__ == "magi.config.lifecycle"
    assert MessageBusModule.__module__ == "magi.events.lifecycle"
    assert PluginSystemModule.__module__ == "magi.plugins.lifecycle"


def test_bootstrap_builds_expected_front_of_layer_order() -> None:
    """Verify bootstrap builds lifecycle modules in expected order (first 4 layers)."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    modules = build_runtime_modules(RuntimeBootstrapContext())

    assert [module.name for module in modules[:4]] == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
        "runtime_plugin_system",
    ]


def test_capability_and_memory_layers_own_their_lifecycle_modules() -> None:
    """Verify capability and memory layers own their lifecycle modules."""
    from magi.context.lifecycle import ContextModule
    from magi.llm.lifecycle import LLMRuntimeModule
    from magi.memory.lifecycle import MemoryStoreModule
    from magi.personality.lifecycle import PersonalityModule
    from magi.tools.lifecycle import ToolsModule

    assert LLMRuntimeModule.__module__ == "magi.llm.lifecycle"
    assert ToolsModule.__module__ == "magi.tools.lifecycle"
    assert MemoryStoreModule.__module__ == "magi.memory.lifecycle"
    assert PersonalityModule.__module__ == "magi.personality.lifecycle"
    assert ContextModule.__module__ == "magi.context.lifecycle"


def test_bootstrap_builds_expected_middle_layer_order() -> None:
    """Verify bootstrap builds lifecycle modules through context layer."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    modules = build_runtime_modules(RuntimeBootstrapContext())

    # Check that modules 0-9 match expected order
    assert [module.name for module in modules[:10]] == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
        "runtime_plugin_system",
        "runtime_llm",
        "runtime_memory",
        "runtime_tools",
        "runtime_personality",
        "runtime_sensor_executor",
        "runtime_context",
    ]


def test_runtime_domain_layers_own_their_lifecycle_modules() -> None:
    """Verify runtime-domain layers own their lifecycle modules."""
    from magi.agent.lifecycle import AgentRuntimeModule, AgentScheduleRegistrationModule
    from magi.awareness.lifecycle import SensorExecutorModule
    from magi.scheduler.lifecycle import SchedulerModule
    from magi.timeline.lifecycle import TimelineModule

    assert SensorExecutorModule.__module__ == "magi.awareness.lifecycle"
    assert AgentRuntimeModule.__module__ == "magi.agent.lifecycle"
    assert AgentScheduleRegistrationModule.__module__ == "magi.agent.lifecycle"
    assert TimelineModule.__module__ == "magi.timeline.lifecycle"
    assert SchedulerModule.__module__ == "magi.scheduler.lifecycle"


def test_bootstrap_builds_expected_full_layer_order() -> None:
    """Verify bootstrap builds all lifecycle modules in expected order."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    modules = build_runtime_modules(RuntimeBootstrapContext())

    assert [module.name for module in modules] == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
        "runtime_plugin_system",
        "runtime_llm",
        "runtime_memory",
        "runtime_tools",
        "runtime_personality",
        "runtime_sensor_executor",
        "runtime_context",
        "runtime_agent_core",
        "runtime_timeline",
        "runtime_scheduler",
        "runtime_agent_scheduler",
        "runtime_exports",
        "runtime_other_dependencies",
    ]


def test_bootstrap_uses_outer_bootstrap_package() -> None:
    """Verify bootstrap entrypoints are exposed from magi.bootstrap."""
    import magi.bootstrap.backend as backend_bootstrap

    assert backend_bootstrap.RuntimeBootstrapContext.__module__ == "magi.bootstrap.context"


def test_maintenance_runtime_primitives_live_in_core() -> None:
    """Verify maintenance primitives are no longer owned by the runtime package."""
    from magi.core.maintenance import MaintenanceConfig, MaintenanceDaemon

    assert MaintenanceConfig.__module__ == "magi.core.maintenance"
    assert MaintenanceDaemon.__module__ == "magi.core.maintenance"


def test_message_bus_service_access_lives_in_events() -> None:
    """Verify message bus service access is owned by the events layer."""
    from magi.events.service_access import get_message_bus, set_message_bus

    assert get_message_bus.__module__ == "magi.events.service_access"
    assert set_message_bus.__module__ == "magi.events.service_access"


def test_current_personality_state_lives_in_personality() -> None:
    """Verify current personality state access is owned by the personality layer."""
    from magi.personality.current_state import get_current_personality, set_current_personality

    assert get_current_personality.__module__ == "magi.personality.current_state"
    assert set_current_personality.__module__ == "magi.personality.current_state"


def test_skills_service_access_lives_in_skills() -> None:
    """Verify shared skills service access is owned by the skills layer."""
    from magi.skills.service_access import init_skills_module, get_skill_executor

    assert init_skills_module.__module__ == "magi.skills.service_access"
    assert get_skill_executor.__module__ == "magi.skills.service_access"


def test_runtime_package_is_removed() -> None:
    """Verify the legacy top-level runtime package no longer exposes runtime APIs."""
    runtime_pkg = importlib.import_module("magi.runtime")

    assert not hasattr(runtime_pkg, "get_agent_runtime")


def test_scheduler_module_does_not_import_domain_contributors() -> None:
    """Verify scheduler lifecycle no longer imports domain schedule contributors."""
    scheduler_lifecycle = Path(__file__).resolve().parents[2] / "src/magi/scheduler/lifecycle.py"
    source = scheduler_lifecycle.read_text(encoding="utf-8")

    assert "TimelineSchedulerContrib" not in source
    assert "AgentSchedulerContrib" not in source
    assert "ActionSchedulerContrib" not in source
