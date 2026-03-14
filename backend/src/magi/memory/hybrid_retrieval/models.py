"""Contracts for hybrid memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class RetrievalQuery:
    """Query contract for memory retrieval."""

    query: str
    user_id: Optional[str]
    session_id: Optional[str]
    time_range: Dict[str, Any]
    query_mode: Literal["detail", "summary", "experience", "graph", "strategy"]
    source_filters: List[str] = field(default_factory=list)
    domain_filters: List[str] = field(default_factory=list)
    limit: int = 10


@dataclass
class RetrievalPayload:
    """Prompt-consumable retrieval result."""

    l0_workbench: List[Dict[str, Any]] = field(default_factory=list)
    l1_events: List[Dict[str, Any]] = field(default_factory=list)
    l2_entity_cards: List[Dict[str, Any]] = field(default_factory=list)
    l2_relationships: List[Dict[str, Any]] = field(default_factory=list)
    l3_reflections: List[Dict[str, Any]] = field(default_factory=list)
    l4_procedures: List[Dict[str, Any]] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)

