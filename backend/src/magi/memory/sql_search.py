"""Small SQL helpers for substring search over list endpoints."""

from __future__ import annotations

from typing import Any, Iterable


def normalized_search_query(query: str | None) -> str:
    """Return the normalized query used by SQL LIKE filters."""
    return str(query or "").strip().casefold()


def escaped_like_pattern(query: str) -> str:
    """Escape wildcard characters before building a LIKE pattern."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def build_like_search_clause(fields: Iterable[str], query: str | None) -> tuple[str, list[Any]]:
    """Build a safe case-insensitive LIKE clause for the supplied SQL fields."""
    normalized = normalized_search_query(query)
    field_list = [field for field in fields if field]
    if not normalized or not field_list:
        return "", []

    pattern = escaped_like_pattern(normalized)
    clauses = [
        f"LOWER(CAST(COALESCE({field}, '') AS TEXT)) LIKE ? ESCAPE '\\'"
        for field in field_list
    ]
    return f" AND ({' OR '.join(clauses)})", [pattern] * len(clauses)
