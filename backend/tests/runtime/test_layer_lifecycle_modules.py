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
    assert hasattr(context, "plugins")
    assert hasattr(context, "skills")
    assert hasattr(context, "agent_runtime")
    assert hasattr(context, "scheduler")


def test_require_initialized_raises_for_missing_value() -> None:
    """Verify require_initialized raises RuntimeError for None values."""
    from magi.bootstrap.context import require_initialized

    with pytest.raises(RuntimeError, match="missing_field is not initialized"):
        require_initialized(None, "missing_field")

    # Verify it returns the value when not None
    assert require_initialized("value", "field") == "value"


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


def test_bootstrap_builds_expected_middle_layer_order() -> None:
    """Verify bootstrap builds lifecycle modules through context layer."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    modules = build_runtime_modules(RuntimeBootstrapContext())

    # Check that modules 0-10 match expected order
    assert [module.name for module in modules[:11]] == [
        "runtime_core_dependencies",
        "runtime_configuration",
        "runtime_message_bus",
        "runtime_plugin_system",
        "runtime_llm",
        "runtime_memory",
        "runtime_tools",
        "runtime_skills",
        "runtime_personality",
        "runtime_sensor_hub",
        "runtime_context",
    ]


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
        "runtime_skills",
        "runtime_personality",
        "runtime_sensor_hub",
        "runtime_context",
        "runtime_agent_core",
        "runtime_timeline",
        "runtime_scheduler",
        "runtime_agent_scheduler",
        "runtime_action_scheduler",
        "runtime_timeline_scheduler",
        "runtime_exports",
        "runtime_other_dependencies",
    ]


def test_tools_module_does_not_initialize_shared_skills_runtime() -> None:
    """Verify tools lifecycle does not own shared skills initialization."""
    tools_lifecycle = Path(__file__).resolve().parents[2] / "src/magi/tools/lifecycle.py"
    source = tools_lifecycle.read_text(encoding="utf-8")

    assert "init_skills_module" not in source


def test_legacy_runtime_package_files_are_removed() -> None:
    """Verify the obsolete top-level runtime package files are deleted."""
    src_root = Path(__file__).resolve().parents[2] / "src/magi"

    assert not (src_root / "runtime/__init__.py").exists()
    assert not (src_root / "runtime/bootstrap.py").exists()


def test_scheduler_module_does_not_import_domain_contributors() -> None:
    """Verify scheduler lifecycle no longer imports domain schedule contributors."""
    scheduler_lifecycle = Path(__file__).resolve().parents[2] / "src/magi/scheduler/lifecycle.py"
    source = scheduler_lifecycle.read_text(encoding="utf-8")

    assert "TimelineSchedulerContrib" not in source
    assert "AgentSchedulerContrib" not in source
    assert "ActionSchedulerContrib" not in source


def test_awareness_lifecycle_owns_action_runtime_primitives() -> None:
    """Verify awareness lifecycle does not import action runtime primitives from core.runtime."""
    awareness_lifecycle = Path(__file__).resolve().parents[2] / "src/magi/awareness/lifecycle.py"
    source = awareness_lifecycle.read_text(encoding="utf-8")

    assert "core.runtime.action_executor" not in source


def test_bootstrap_builder_uses_sensors_and_actions_module_name() -> None:
    builder_source = (Path(__file__).resolve().parents[2] / "src/magi/bootstrap/builder.py").read_text(encoding="utf-8")
    awareness_source = (Path(__file__).resolve().parents[2] / "src/magi/awareness/lifecycle.py").read_text(encoding="utf-8")

    assert "SensorHubModule" not in builder_source
    assert "class SensorHubModule" not in awareness_source
    assert "SensorsAndActionsModule" in builder_source
    assert "class SensorsAndActionsModule" in awareness_source
    assert "core.runtime.action_scheduler_contrib" not in awareness_source


def test_core_runtime_no_longer_exports_action_executor() -> None:
    """Verify core.runtime stops exporting the legacy ActionExecutor symbol."""
    runtime_init = Path(__file__).resolve().parents[2] / "src/magi/core/runtime/__init__.py"
    source = runtime_init.read_text(encoding="utf-8")

    assert "ActionExecutor" not in source


def test_core_package_does_not_export_legacy_loop_runtime() -> None:
    """Verify core package no longer exports legacy loop runtime symbols."""
    core_init = Path(__file__).resolve().parents[2] / "src/magi/core/__init__.py"
    source = core_init.read_text(encoding="utf-8")

    assert "LoopEngine" not in source
    assert "LoopStrategy" not in source
    assert "CompleteAgent" not in source


def test_legacy_loop_and_processing_paths_are_removed() -> None:
    """Verify obsolete runtime loop and processing paths are deleted."""
    src_root = Path(__file__).resolve().parents[2] / "src/magi"
    processing_dir = src_root / "processing"

    assert not (src_root / "core/loop.py").exists()
    assert not (src_root / "core/complete_agent.py").exists()
    assert not (processing_dir / "__init__.py").exists()
    assert not list(processing_dir.glob("*.py"))


def test_legacy_context_builder_path_is_removed() -> None:
    """Verify legacy context builder implementation is deleted."""
    src_root = Path(__file__).resolve().parents[2] / "src/magi"
    context_dir = src_root / "context"

    assert not (context_dir / "builder.py").exists()


def test_active_chat_context_path_does_not_import_legacy_builder() -> None:
    """Verify chat task-agent prompt flow no longer depends on context.builder."""
    src_root = Path(__file__).resolve().parents[2] / "src/magi"
    files = [
        src_root / "agent/task_agents/chat/prompt_service.py",
        src_root / "agent/task_agents/chat/handlers.py",
        src_root / "agent/task_agents/chat/planning_service.py",
        src_root / "context/__init__.py",
    ]

    for file_path in files:
        source = file_path.read_text(encoding="utf-8")
        assert "context.builder" not in source
        assert "from .builder import Scenario" not in source
