"""Container-backed runtime binding helpers for API and transport consumers."""

from __future__ import annotations

from .container import get_container


def _require_binding(provider_name: str):
    container = get_container()
    provider = getattr(container, provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def require_message_bus():
    """Return the active message bus binding."""
    return _require_binding("message_bus")


def require_runtime_command_queue():
    """Return the active runtime command queue binding."""
    return _require_binding("runtime_command_queue")


def require_agent_runtime():
    """Return the active agent runtime binding."""
    return _require_binding("agent_runtime")


def require_memory_integration():
    """Return the active memory integration binding."""
    return _require_binding("memory_integration")


def require_unified_memory():
    """Return the active unified memory binding."""
    return _require_binding("unified_memory")


def require_hybrid_retrieval_service():
    """Return the active hybrid retrieval service binding."""
    return _require_binding("hybrid_retrieval_service")


def require_scenario_llm_pool():
    """Return the active scenario LLM pool binding."""
    return _require_binding("scenario_llm_pool")


def require_scheduler_service():
    """Return the active scheduler service binding."""
    return _require_binding("scheduler_service")


def require_timeline_scheduler_contrib():
    """Return the active timeline scheduler contributor binding."""
    return _require_binding("timeline_scheduler_contrib")


def require_other_memory():
    """Return the runtime-owned other-memory binding."""
    return _require_binding("other_memory")


def require_user_message_sensor():
    """Return the shared user-message sensor binding."""
    return _require_binding("user_message_sensor")


def require_plugin_manager():
    """Return the active plugin manager binding."""
    return _require_binding("plugin_manager")


def require_sensor_registry():
    """Return the active sensor registry binding."""
    return _require_binding("sensor_registry")


def require_action_registry():
    """Return the active action registry binding."""
    return _require_binding("action_registry")


def require_skill_indexer():
    """Return the shared skill indexer binding."""
    return _require_binding("skill_indexer")


def require_skill_loader():
    """Return the shared skill loader binding."""
    return _require_binding("skill_loader")


def require_skill_runner():
    """Return the shared skill runner binding."""
    return _require_binding("skill_runner")


def require_runtime_trace_store():
    """Return the active runtime trace store binding."""
    return _require_binding("runtime_trace_store")
