"""Tests for process-role bootstrap ownership."""

from __future__ import annotations


def test_runtime_dependencies_resolve_before_recovery_and_dispatch():
    from magi.bootstrap.builder import build_runtime_modules
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.bootstrap.lifecycle import ModuleLifecycleOrchestrator

    modules = build_runtime_modules(RuntimeBootstrapContext())
    order = list(ModuleLifecycleOrchestrator(reversed(modules)).snapshot())
    by_name = {module.name: module for module in modules}
    required_edges = {
        "runtime_exports": {"runtime_base_exports", "runtime_trace"},
        "runtime_chat_forgetting_recovery": {"runtime_chat_store", "runtime_memory"},
        "runtime_chat_assistant_memory_projection": {
            "runtime_chat_store",
            "runtime_chat_projector",
            "runtime_memory",
            "runtime_memory_ingestion_subscriber",
            "runtime_chat_forgetting_recovery",
        },
        "runtime_chat_delivery_recovery": {
            "runtime_chat_store",
            "runtime_chat_projector",
            "runtime_command_queue",
            "runtime_agent_core",
            "runtime_memory_ingestion_subscriber",
        },
        "runtime_command_processor": {
            "runtime_chat_forgetting_recovery",
            "runtime_chat_assistant_memory_projection",
            "runtime_chat_delivery_recovery",
        },
    }
    for consumer, prerequisites in required_edges.items():
        for prerequisite in prerequisites:
            assert order.index(prerequisite) < order.index(consumer), (prerequisite, consumer)
    assert by_name["runtime_memory"].start_memory_integration is True
