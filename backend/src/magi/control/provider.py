"""Container-backed providers for control-plane runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from .common import InteractionBroker
    from .permission.brokered_prompter import PendingPermissionRegistry
    from .permission.rules import PermissionRuleStore
    from .session_store import ControlSessionStore
    from .settings_manager import ControlSettingsManager


def _require_control_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def resolve_control_session_store() -> "ControlSessionStore":
    """Return the active control-plane session store binding."""
    return cast("ControlSessionStore", _require_control_binding("control_session_store"))


def resolve_control_settings_manager() -> "ControlSettingsManager":
    """Return the active control-plane settings manager binding."""
    return cast("ControlSettingsManager", _require_control_binding("control_settings_manager"))


def resolve_permission_rule_store() -> "PermissionRuleStore":
    """Return the active permission rule store binding."""
    return cast("PermissionRuleStore", _require_control_binding("permission_rule_store"))


def resolve_control_interaction_broker() -> "InteractionBroker":
    """Return the active control-plane interaction broker binding."""
    return cast("InteractionBroker", _require_control_binding("control_interaction_broker"))


def resolve_pending_permission_registry() -> "PendingPermissionRegistry":
    """Return the active pending-permission registry binding."""
    return cast("PendingPermissionRegistry", _require_control_binding("pending_permission_registry"))
