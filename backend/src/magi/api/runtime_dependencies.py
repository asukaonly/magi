"""Explicit collaborators supplied by the composition root to product APIs."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from magi.core.container import optional_binding, require_binding


@dataclass(frozen=True, slots=True)
class ApiRuntimeDependencies:
    outreach_service: Any = None
    plugin_user_content_clear: Any = None
    channels_module: Any = None
    control_user_content_clear: Any = None
    chat_memory_projection_clear: Any = None
    self_memory: Any = None
    runtime_trace_store: Any = None
    runtime_trace_subscriber: Any = None
    llm_usage_subscriber: Any = None
    llm_usage_store: Any = None
    llm_adapter_ready: bool = False
    full_clear_recovery_pending: bool = False


def get_api_runtime_dependencies() -> ApiRuntimeDependencies:
    return optional_binding("api_runtime_dependencies") or ApiRuntimeDependencies()

def require_chat_portrait_service() -> Any:
    """Return the active chat portrait service binding."""
    return require_binding("chat_portrait_service")

def require_chat_read_service() -> Any:
    """Return the active chat read service binding."""
    return require_binding("chat_read_service")

def require_chat_attachment_ingestion_service() -> Any:
    """Return the active chat attachment ingestion service binding."""
    return require_binding("chat_attachment_ingestion_service")

def require_chat_surface_write_service() -> Any:
    """Return the active chat surface write service binding."""
    return require_binding("chat_surface_write_service")

def require_chat_forgetting_service() -> Any:
    """Build the chat deletion coordinator from active runtime bindings."""
    return require_binding("chat_forgetting_service")

def require_user_message_dispatcher() -> Any:
    """Return the active user-message dispatcher binding."""
    return require_binding("user_message_dispatcher")
