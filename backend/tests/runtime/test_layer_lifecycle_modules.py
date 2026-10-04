"""Tests for layer-owned lifecycle modules and bootstrap context."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_require_initialized_raises_for_missing_value() -> None:
    """Verify require_initialized raises RuntimeError for None values."""
    from magi.bootstrap.context import require_initialized

    with pytest.raises(RuntimeError, match="missing_field is not initialized"):
        require_initialized(None, "missing_field")

    # Verify it returns the value when not None
    assert require_initialized("value", "field") == "value"


def test_execution_starts_after_its_required_exports() -> None:
    """Prevent queue consumers and scheduled jobs from observing missing bindings."""
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
    executor_index = resolved.index("runtime_source_sync_executor")

    assert resolved.index("runtime_scheduler_exports") < activation_index
    assert resolved.index("runtime_source_scheduler") < executor_index
    assert activation_index < executor_index
    assert resolved.index("runtime_exports") < resolved.index("runtime_command_processor")


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
        "runtime_initialization_state",
        "runtime_memory_restore_recovery",
    ], (
        "schema migrations must run before every database consumer; only orphan "
        "cleanup, core paths, initialization state, and memory restore recovery may precede them. "
        f"Got before-migrations: {resolved[:migrations_idx]}"
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
    assert "exports_and_maintenance=runtime_base_exports" in phase_plan


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
    assert "from ..core.runtime import SourceHub" not in source
    assert "from .source_hub import SourceHub" in source
