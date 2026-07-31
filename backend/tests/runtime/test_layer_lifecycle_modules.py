"""Tests for layer-owned lifecycle modules and bootstrap context."""

from __future__ import annotations

import re
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


def test_bootstrap_builds_expected_full_layer_order() -> None:
    """Verify bootstrap builds all lifecycle modules in expected order."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    modules = build_runtime_modules(RuntimeBootstrapContext())

    assert [module.name for module in modules] == [
        "subprocess_orphan_cleanup",
        "runtime_core_dependencies",
        "runtime_database_migrations",
        "runtime_identity",
        "runtime_configuration",
        "runtime_command_queue",
        "runtime_message_bus",
        "runtime_chat_store",
        "runtime_plugin_system",
        "runtime_llm",
        "runtime_memory",
        "runtime_chat_forgetting_recovery",
        "runtime_media_registry",
        "runtime_location",
        "runtime_manual_entries",
        "runtime_history_imports",
        "runtime_memory_ingestion_subscriber",
        "runtime_llm_usage_subscriber",
        "runtime_chat_projector",
        "runtime_chat_assistant_memory_projection",
        "runtime_control_transcript_subscriber",
        "runtime_trace",
        "runtime_trace_subscriber",
        "runtime_hooks",
        "runtime_first_party_tools",
        "runtime_tools",
        "runtime_skills",
        "runtime_mcp",
        "runtime_personality",
        "runtime_sensor_hub",
        "runtime_context",
        "runtime_agent_core",
        "runtime_chat_delivery_recovery",
        "runtime_command_processor",
        "runtime_plugin_ingress_processor",
        "runtime_timeline",
        "runtime_timeline_subscriber",
        "runtime_kg_subscriber",
        "runtime_sensor_state_subscriber",
        "runtime_scheduler",
        "runtime_agent_schedule_registration",
        "runtime_sensor_scheduler",
        "runtime_exports",
        "runtime_control_plane",
        "runtime_l1_maintenance_scheduler",
        "runtime_l2_maintenance_scheduler",
        "runtime_l2_consolidation_scheduler",
        "runtime_l2_derive_scheduler",
        "runtime_l3_summary_scheduler",
        "runtime_l3_maintenance_scheduler",
        "runtime_l4_maintenance_scheduler",
        "runtime_timeline_schedulers",
        "runtime_operational_gc_scheduler",
        "runtime_other_dependencies",
        "runtime_channels",
        "runtime_outreach",
        "runtime_scheduler_activation",
        "runtime_sensor_sync_executor",
    ]


def test_background_schedule_execution_starts_after_all_registrations() -> None:
    """Keep schedule writers ahead of scheduler and sensor execution."""
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.bootstrap.lifecycle import ModuleLifecycleOrchestrator

    resolved = [
        module.name
        for module in ModuleLifecycleOrchestrator(
            build_runtime_modules(RuntimeBootstrapContext())
        )._modules
    ]
    activation_index = resolved.index("runtime_scheduler_activation")
    executor_index = resolved.index("runtime_sensor_sync_executor")
    schedule_registrations = [
        name
        for name in resolved
        if name.endswith("_scheduler") or name == "runtime_agent_schedule_registration"
    ]

    assert all(resolved.index(name) < activation_index for name in schedule_registrations)
    assert activation_index < executor_index


def test_schema_migrations_run_before_any_db_consuming_module() -> None:
    """Regression: in the orchestrator's RESOLVED (topologically-sorted) order,
    schema migrations must precede every module that opens a migrated DB.

    The builder's *list* order is not the run order — ``ModuleLifecycleOrchestrator``
    re-sorts by declared dependencies (FIFO Kahn's algorithm). A dependency-free
    module sits in the initial queue and runs ahead of ``DatabaseMigrationModule``
    (which must wait for ``runtime_core_dependencies``). That is exactly how
    ``runtime_control_plane`` (no declared deps) once ran before migrations and
    read ``permission_rules`` before the table existed (fresh-DB startup crash).

    Only the two modules that legitimately precede migrations — the orphan-process
    sweep and core dependencies (which provides runtime paths) — may appear first.
    """
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.bootstrap.lifecycle import ModuleLifecycleOrchestrator

    resolved = [
        m.name
        for m in ModuleLifecycleOrchestrator(
            build_runtime_modules(RuntimeBootstrapContext())
        )._modules
    ]
    migrations_idx = resolved.index("runtime_database_migrations")
    assert resolved[:migrations_idx] == [
        "subprocess_orphan_cleanup",
        "runtime_core_dependencies",
    ], (
        "schema migrations must run before every other module; only orphan "
        f"cleanup + core deps may precede them. Got before-migrations: {resolved[:migrations_idx]}"
    )


def test_runtime_worker_phase_metadata_matches_built_module_order() -> None:
    """Verify exported phase metadata stays aligned with the actual builder output."""
    from magi.bootstrap import (
        describe_runtime_worker_phase_plan,
        get_runtime_worker_module_order,
        get_runtime_worker_phase_definitions,
    )
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    phase_definitions = get_runtime_worker_phase_definitions()
    assert [phase.phase_id for phase in phase_definitions] == [
        "infrastructure",
        "stateful_services",
        "processing",
        "exports_and_maintenance",
    ]

    modules = build_runtime_modules(RuntimeBootstrapContext())
    assert tuple(module.name for module in modules) == get_runtime_worker_module_order()

    phase_plan = describe_runtime_worker_phase_plan()
    assert "infrastructure=subprocess_orphan_cleanup" in phase_plan
    assert "exports_and_maintenance=runtime_exports" in phase_plan


def test_runtime_worker_phase_docs_match_built_module_order() -> None:
    """Keep the durable architecture guide aligned with the runtime manifest."""
    from magi.bootstrap import get_runtime_worker_module_order

    docs_path = (
        Path(__file__).resolve().parents[3]
        / "docs/task-agent-runtime-architecture.md"
    )
    source = docs_path.read_text(encoding="utf-8")
    sequence = source.split(
        "The current runtime-worker sequence in "
        "`bootstrap/runtime_worker_builder.py` is:",
        1,
    )[1].split("Important rule: bootstrap order", 1)[0]
    documented_order = tuple(
        re.findall(r"^\d+\. `([^`]+)`$", sequence, flags=re.MULTILINE)
    )

    assert documented_order == get_runtime_worker_module_order()


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


def test_legacy_memory_message_bus_backend_is_removed() -> None:
    """Verify the obsolete in-memory message bus backend is deleted."""
    src_root = Path(__file__).resolve().parents[2] / "src/magi"

    assert not (src_root / "events/memory_backend.py").exists()


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
    assert "from ..core.runtime import SensorHub" not in source
    assert "from .sensor_hub import SensorHub" in source


def test_bootstrap_builder_uses_sensor_module_name() -> None:
    builder_source = (Path(__file__).resolve().parents[2] / "src/magi/bootstrap/builder.py").read_text(encoding="utf-8")
    runtime_worker_builder_source = (
        Path(__file__).resolve().parents[2] / "src/magi/bootstrap/runtime_worker_builder.py"
    ).read_text(encoding="utf-8")
    awareness_source = (Path(__file__).resolve().parents[2] / "src/magi/awareness/lifecycle.py").read_text(encoding="utf-8")

    assert "SensorHubModule" not in builder_source
    assert "SensorHubModule" not in runtime_worker_builder_source
    assert "class SensorHubModule" not in awareness_source
    assert "SensorModule" in runtime_worker_builder_source
    assert "class SensorModule" in awareness_source
    assert "core.runtime.action_scheduler_contrib" not in awareness_source


def test_core_runtime_no_longer_exports_action_executor() -> None:
    """Verify core.runtime stops exporting the legacy ActionExecutor symbol."""
    runtime_init = Path(__file__).resolve().parents[2] / "src/magi/core/runtime/__init__.py"
    assert not runtime_init.exists()


def test_agent_runtime_package_owns_runtime_primitives() -> None:
    """Verify runtime primitives move from core.runtime into agent.runtime."""
    agent_runtime_init = Path(__file__).resolve().parents[2] / "src/magi/agent/runtime/__init__.py"
    source = agent_runtime_init.read_text(encoding="utf-8")

    assert "AgentRuntime" in source
    assert "RouterAgent" in source
    assert "TaskAgent" in source
    assert "TaskAgentManager" in source
    assert "TaskAgentType" in source
    assert "FactRecord" in source


def test_awareness_package_owns_sensor_hub_and_sensor_event() -> None:
    """Verify awareness package owns sensor-hub runtime primitives."""
    sensor_hub_source = (Path(__file__).resolve().parents[2] / "src/magi/awareness/sensor_hub.py").read_text(encoding="utf-8")
    contracts_source = (Path(__file__).resolve().parents[2] / "src/magi/awareness/contracts.py").read_text(encoding="utf-8")

    assert "class SensorHub" in sensor_hub_source
    assert "class SensorEvent" in contracts_source


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
        src_root / "chat/task_agent/prompt_service.py",
        src_root / "agent/task_agents/handlers/handlers.py",
        src_root / "chat/task_agent/planning_service.py",
        src_root / "context/__init__.py",
    ]

    for file_path in files:
        source = file_path.read_text(encoding="utf-8")
        assert "context.builder" not in source
        assert "from .builder import Scenario" not in source
