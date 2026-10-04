"""Tests for layer-owned lifecycle modules and bootstrap context."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing,expected_error", [("message_bus", "message bus"), ("unified_memory", "unified memory")]
)
async def test_source_lifecycle_rejects_missing_dependencies_before_publishing_bindings(
    missing, expected_error
):
    from magi.awareness.lifecycle import SourceModule
    from magi.bootstrap.context import RuntimeBootstrapContext

    context = RuntimeBootstrapContext()
    context.message_bus.message_bus = None if missing == "message_bus" else object()
    context.memory.unified_memory = None if missing == "unified_memory" else object()
    with pytest.raises(RuntimeError, match=f"{expected_error} is not initialized"):
        await SourceModule(context).init()
    assert context.agent_runtime.source_hub is None
    assert context.agent_runtime.event_emitter is None
    assert context.agent_runtime.source_ingestion_gateway is None


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


def test_phase_manifest_logs_and_architecture_guide_describe_built_modules():
    from magi.bootstrap import (
        describe_runtime_worker_phase_plan,
        get_runtime_worker_module_order,
        get_runtime_worker_phase_definitions,
    )
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext

    phases = get_runtime_worker_phase_definitions()
    assert phases and len({phase.phase_id for phase in phases}) == len(phases)
    flattened = tuple(name for phase in phases for name in phase.module_names)
    assert flattened == tuple(
        module.name for module in build_runtime_modules(RuntimeBootstrapContext())
    )
    assert flattened == get_runtime_worker_module_order()
    assert len(flattened) == len(set(flattened))
    log_groups = dict(
        section.split("=", 1) for section in describe_runtime_worker_phase_plan().split(" | ")
    )
    assert list(log_groups) == [phase.phase_id for phase in phases]
    for phase in phases:
        assert phase.title and phase.description and phase.module_names
        assert log_groups[phase.phase_id].split(",") == list(phase.module_names)
    source = (
        Path(__file__).resolve().parents[3] / "docs/task-agent-runtime-architecture.md"
    ).read_text()
    sequence = source.split(
        "The current runtime-worker sequence in `bootstrap/runtime_worker_builder.py` is:", 1
    )[1].split("Important rule: bootstrap order", 1)[0]
    assert tuple(re.findall(r"^\d+\. `([^`]+)`$", sequence, flags=re.MULTILINE)) == flattened


@pytest.mark.asyncio
async def test_source_lifecycle_owns_isolated_queues_and_emission_bindings():
    from unittest.mock import AsyncMock
    from magi.awareness.contracts import SourceEvent
    from magi.awareness.lifecycle import SourceModule
    from magi.bootstrap.context import RuntimeBootstrapContext

    contexts = [RuntimeBootstrapContext(), RuntimeBootstrapContext()]
    modules = [SourceModule(context) for context in contexts]
    for context, module in zip(contexts, modules, strict=True):
        context.message_bus.message_bus = AsyncMock()
        context.memory.unified_memory = object()
        await module.init()
    try:
        event = SourceEvent(
            source_name="calendar", event_type="meeting", payload={"id": "first-only"}
        )
        await contexts[0].agent_runtime.source_hub.push_source_event(event)
        assert await contexts[0].agent_runtime.source_hub.get_batch(timeout_seconds=0.01) == [event]
        assert await contexts[1].agent_runtime.source_hub.get_batch(timeout_seconds=0.01) == []
        for index, context in enumerate(contexts):
            await context.agent_runtime.event_emitter.emit_runtime_event(
                event_type="completed", payload={"owner": index}
            )
            context.message_bus.message_bus.publish.assert_awaited_once()
            assert context.message_bus.message_bus.publish.await_args.args[0].data == {
                "owner": index
            }
        await modules[0].shutdown()
        assert contexts[0].agent_runtime.source_hub is None
        assert contexts[0].agent_runtime.event_emitter is None
        assert contexts[0].agent_runtime.source_ingestion_gateway is None
        await contexts[1].agent_runtime.source_hub.push_source_event(event)
        assert await contexts[1].agent_runtime.source_hub.get_batch(timeout_seconds=0.01) == [event]
    finally:
        for module in modules:
            await module.shutdown()
