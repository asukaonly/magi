from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .event_contracts import MemoryEvent

WILDCARD_EVENT_TYPES: frozenset[str] = frozenset({"*"})


@dataclass
class FanOutContext:
    markers: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerIngestResult:
    layer_name: str
    ok: bool
    markers: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MemoryLayer(Protocol):
    layer_name: str
    accepts_event_types: frozenset[str]
    requires_write_lock: bool
    required_for_acceptance: bool

    def accepts(self, event: MemoryEvent, ctx: FanOutContext) -> bool: ...
    async def ingest(self, event: MemoryEvent, ctx: FanOutContext) -> LayerIngestResult: ...
