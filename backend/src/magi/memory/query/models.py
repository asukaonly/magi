"""Data models for memory query requests and results."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MemoryQueryRequest:
    """Request to query memories across L1-L5 layers."""

    query: str
    time_range: Dict[str, Any]
    data_types: Optional[List[str]] = None
    limit: Optional[int] = None


@dataclass
class MemoryQueryResult:
    """Result from memory query execution."""

    status: str  # "success" | "confirm_required" | "empty" | "denied"
    confirm_prompt: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    query_meta: Optional[Dict[str, Any]] = None
