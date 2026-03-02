"""Compatibility wrapper around the L5 capability memory implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .l5_capabilities import CapabilityMemory


@dataclass
class CapabilityMemoryRecord:
    """Legacy capability record format kept for backwards compatibility."""

    trigger_pattern: Dict[str, Any]
    action: Dict[str, Any]
    success_rate: float = 1.0
    usage_count: int = 1
    created_at: float = 0.0
    last_used_at: Optional[float] = None
    source: str = "experience"
    metadata: Dict[str, Any] = field(default_factory=dict)


class CapabilityStore:
    """Legacy API surface backed by the new CapabilityMemory store."""

    def __init__(self, db_path: str = "~/.magi/data/memories/capabilities.db", chromadb_path: str = ""):
        _ = chromadb_path  # kept for signature compatibility
        self._backend = CapabilityMemory(persist_path=db_path)

    async def init(self) -> None:
        self._backend.get_statistics()

    async def save(self, capability: CapabilityMemoryRecord) -> None:
        context = capability.trigger_pattern if isinstance(capability.trigger_pattern, dict) else {}
        action = capability.action if isinstance(capability.action, dict) else {}
        self._backend.record_attempt(
            task_id=action.get("task_id", "legacy_capability"),
            context=context,
            action=action,
            success=capability.success_rate >= 0.5,
            duration=0.0,
            error=None,
        )

    async def find(self, perception_pattern: Dict[str, Any]) -> Optional[CapabilityMemoryRecord]:
        capability = self._backend.find_capability(perception_pattern)
        if not capability:
            return None
        return CapabilityMemoryRecord(
            trigger_pattern=capability.trigger_pattern,
            action=capability.action,
            success_rate=capability.success_rate,
            usage_count=capability.usage_count,
            created_at=capability.created_at,
            last_used_at=capability.last_used,
            source="experience",
        )

    async def update_success_rate(self, capability_id: str, success: bool) -> None:
        capability = self._backend.get_capability(capability_id)
        if not capability:
            return
        self._backend.record_attempt(
            task_id=capability_id,
            context={"event_type": "legacy_update"},
            action=capability.action,
            success=success,
            duration=0.0,
            error=None,
        )

    async def get_all_capabilities(self) -> List[CapabilityMemoryRecord]:
        capabilities = self._backend.get_all_capabilities()
        return [
            CapabilityMemoryRecord(
                trigger_pattern=cap.trigger_pattern,
                action=cap.action,
                success_rate=cap.success_rate,
                usage_count=cap.usage_count,
                created_at=cap.created_at,
                last_used_at=cap.last_used,
                source="experience",
            )
            for cap in capabilities
        ]
