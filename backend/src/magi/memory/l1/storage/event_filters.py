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
        exclude_event_types: Optional[List[str]] = None,
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
        _append_identity_filters(
            parts=parts,
            args=args,
            session_id=session_id,
            user_id=user_id,
            memory_domain=memory_domain,
            event_id=event_id,
            event_type=event_type,
            exclude_event_types=exclude_event_types,
        )
        _append_content_source_filters(
            parts=parts,
            args=args,
            query=query,
            source_filters=source_filters,
            source_item_id=source_item_id,
            idempotency_key=idempotency_key,
        )
        _append_eligibility_scope_filters(
            parts=parts,
            args=args,
            cognition_eligible=cognition_eligible,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        _append_time_filters(parts=parts, args=args, start_time=start_time, end_time=end_time)
        _append_exclusion_filters(
            parts=parts,
            args=args,
            exclude_memory_domain=exclude_memory_domain,
            exclude_retention_class=exclude_retention_class,
        )
        return " AND ".join(parts), args


def _append_identity_filters(
    *,
    parts: list[str],
    args: List[Any],
    session_id: Optional[str],
    user_id: Optional[str],
    memory_domain: Optional[str],
    event_id: Optional[str],
    event_type: Optional[str],
    exclude_event_types: Optional[List[str]],
) -> None:
    _append_equal(parts, args, "session_id", session_id)
    _append_equal(parts, args, "user_id", user_id)
    if memory_domain:
        parts.append("memory_domain = ?")
        args.append(int(MemoryDomain.from_value(memory_domain)))
    _append_equal(parts, args, "event_id", event_id)
    _append_equal(parts, args, "event_type", event_type)
    _append_in(parts, args, "event_type", exclude_event_types, operator="NOT IN")


def _append_content_source_filters(
    *,
    parts: list[str],
    args: List[Any],
    query: Optional[str],
    source_filters: Optional[List[str]],
    source_item_id: Optional[str],
    idempotency_key: Optional[str],
) -> None:
    if query:
        parts.append("LOWER(content) LIKE ?")
        args.append(f"%{str(query).strip().lower()}%")
    _append_in(parts, args, "source", source_filters)
    _append_equal(parts, args, "source_item_id", source_item_id)
    _append_equal(parts, args, "idempotency_key", idempotency_key)


def _append_eligibility_scope_filters(
    *,
    parts: list[str],
    args: List[Any],
    cognition_eligible: Optional[bool],
    l1_retrieval_scopes: Optional[List[str]],
) -> None:
    if cognition_eligible is not None:
        parts.append("cognition_eligible = ?")
        args.append(1 if cognition_eligible else 0)
    if l1_retrieval_scopes is None:
        return
    if not l1_retrieval_scopes:
        parts.append("0 = 1")
        return
    scope_values = [int(L1RetrievalScope.from_value(scope)) for scope in l1_retrieval_scopes]
    _append_in(parts, args, "l1_retrieval_scope", scope_values)


def _append_time_filters(
    *,
    parts: list[str],
    args: List[Any],
    start_time: Optional[float],
    end_time: Optional[float],
) -> None:
    if start_time is not None:
        parts.append("timestamp >= ?")
        args.append(float(start_time))
    if end_time is not None:
        parts.append("timestamp <= ?")
        args.append(float(end_time))


def _append_exclusion_filters(
    *,
    parts: list[str],
    args: List[Any],
    exclude_memory_domain: Optional[str],
    exclude_retention_class: Optional[str],
) -> None:
    _append_excluded_memory_domain(parts, args, exclude_memory_domain)
    _append_excluded_retention_class(parts, args, exclude_retention_class)


def _append_excluded_memory_domain(
    parts: list[str], args: List[Any], exclude_memory_domain: Optional[str]
) -> None:
    if not exclude_memory_domain:
        return
    try:
        parts.append("memory_domain != ?")
        args.append(int(MemoryDomain.from_value(exclude_memory_domain)))
    except (ValueError, KeyError):
        pass


def _append_excluded_retention_class(
    parts: list[str], args: List[Any], exclude_retention_class: Optional[str]
) -> None:
    if not exclude_retention_class:
        return
    try:
        parts.append("retention_class != ?")
        args.append(int(RetentionClass.from_value(exclude_retention_class)))
    except (ValueError, KeyError):
        pass


def _append_equal(parts: list[str], args: List[Any], column: str, value: str | None) -> None:
    if not value:
        return
    parts.append(f"{column} = ?")
    args.append(value)


def _append_in(
    parts: list[str],
    args: List[Any],
    column: str,
    values: List[Any] | None,
    *,
    operator: str = "IN",
) -> None:
    if not values:
        return
    placeholders = ", ".join("?" for _ in values)
    parts.append(f"{column} {operator} ({placeholders})")
    args.extend(values)


__all__ = ["L1EventFilterMixin"]
