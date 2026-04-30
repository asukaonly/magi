"""Container-backed providers for memory-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from . import UnifiedMemoryStore
    from .hybrid_retrieval.service import HybridRetrievalService
    from .integration import MemoryIntegrationModule


def _require_memory_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def get_memory_integration() -> "MemoryIntegrationModule":
    """Return the active memory integration binding."""
    return cast("MemoryIntegrationModule", _require_memory_binding("memory_integration"))


def get_unified_memory() -> "UnifiedMemoryStore":
    """Return the active unified memory binding."""
    return cast("UnifiedMemoryStore", _require_memory_binding("unified_memory"))


def get_hybrid_retrieval_service() -> "HybridRetrievalService":
    """Return the active hybrid retrieval service binding."""
    return cast("HybridRetrievalService", _require_memory_binding("hybrid_retrieval_service"))
