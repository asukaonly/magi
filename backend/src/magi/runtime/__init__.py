"""Runtime orchestration entrypoints (backward compatibility module).

DEPRECATED: Import from magi.bootstrap directly for new code.
This module provides lazy imports to avoid circular dependencies.
"""

from __future__ import annotations


def __getattr__(name: str):
    """Lazy import from magi.bootstrap for backward compatibility."""
    from .. import bootstrap
    return getattr(bootstrap, name)


__all__ = [
    "get_agent_runtime",
    "get_master_agent",
    "get_memory_integration",
    "get_scheduler_service",
    "get_unified_memory",
    "initialize_agent_runtime",
    "initialize_chat_agent",
    "refresh_runtime_llm_config",
    "shutdown_agent_runtime",
    "shutdown_chat_agent",
]
