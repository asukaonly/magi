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


def require_runtime_command_queue():
    """Return the active runtime command queue binding."""
    return _require_binding("runtime_command_queue")


def require_agent_runtime():
    """Return the active agent runtime binding."""
    return _require_binding("agent_runtime")


def require_background_task_manager():
    """Return the active background-task manager binding."""
    return _require_binding("background_task_manager")


def require_control_session_store():
    """Return the active control-plane session store binding."""
    return _require_binding("control_session_store")


def require_control_settings_manager():
    """Return the active control-plane settings manager binding."""
    return _require_binding("control_settings_manager")


def require_permission_rule_store():
    """Return the active permission rule store binding."""
    return _require_binding("permission_rule_store")


def require_control_interaction_broker():
    """Return the active control-plane interaction broker binding."""
    return _require_binding("control_interaction_broker")


def require_pending_permission_registry():
    """Return the active pending-permission registry binding."""
    return _require_binding("pending_permission_registry")
