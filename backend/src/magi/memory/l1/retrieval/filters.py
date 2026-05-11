"""SQL filter builders for L1 event retrieval."""

from __future__ import annotations

from typing import Any, List, Optional

from ...evidence import L1RetrievalScope
from ...event_contracts import MemoryDomain, RetentionClass


class L1EventFilterMixin:
    """Build SQL WHERE clauses for canonical L1 event queries."""

    @staticmethod
    def _build_event_filters(
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_domain: Optional[str] = None,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
        query: Optional[str] = None,
        source_filters: Optional[List[str]] = None,
        source_item_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        cognition_eligible: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        exclude_memory_domain: Optional[str] = None,
        exclude_retention_class: Optional[str] = None,
        l1_retrieval_scopes: Optional[List[str]] = None,
    ) -> tuple[str, List[Any]]:
        """Build WHERE clause and args for event queries."""
        parts = ["deleted_at IS NULL"]
        args: List[Any] = []
        if session_id:
            parts.append("session_id = ?")
            args.append(session_id)
        if user_id:
            parts.append("user_id = ?")
            args.append(user_id)
        if memory_domain:
            parts.append("memory_domain = ?")
            args.append(int(MemoryDomain.from_value(memory_domain)))
        if event_id:
            parts.append("event_id = ?")
            args.append(event_id)
        if event_type:
            parts.append("event_type = ?")
            args.append(event_type)
        if query:
            parts.append("LOWER(content) LIKE ?")
            args.append(f"%{str(query).strip().lower()}%")
        if source_filters:
            placeholders = ", ".join("?" for _ in source_filters)
            parts.append(f"source IN ({placeholders})")
            args.extend(source_filters)
        if source_item_id:
            parts.append("source_item_id = ?")
            args.append(source_item_id)
        if idempotency_key:
            parts.append("idempotency_key = ?")
            args.append(idempotency_key)
        if cognition_eligible is not None:
            parts.append("cognition_eligible = ?")
            args.append(1 if cognition_eligible else 0)
        if l1_retrieval_scopes is not None:
            if not l1_retrieval_scopes:
                parts.append("0 = 1")
            else:
                placeholders = ", ".join("?" for _ in l1_retrieval_scopes)
                parts.append(f"l1_retrieval_scope IN ({placeholders})")
                args.extend(int(L1RetrievalScope.from_value(scope)) for scope in l1_retrieval_scopes)
        if start_time is not None:
            parts.append("timestamp >= ?")
            args.append(float(start_time))
        if end_time is not None:
            parts.append("timestamp <= ?")
            args.append(float(end_time))
        if exclude_memory_domain:
            try:
                parts.append("memory_domain != ?")
                args.append(int(MemoryDomain.from_value(exclude_memory_domain)))
            except (ValueError, KeyError):
                pass
        if exclude_retention_class:
            try:
                parts.append("retention_class != ?")
                args.append(int(RetentionClass.from_value(exclude_retention_class)))
            except (ValueError, KeyError):
                pass
        return " AND ".join(parts), args


__all__ = ["L1EventFilterMixin"]