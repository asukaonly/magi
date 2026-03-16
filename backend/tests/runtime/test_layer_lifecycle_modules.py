"""Tests for layer-owned lifecycle modules and bootstrap context."""

from __future__ import annotations

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
