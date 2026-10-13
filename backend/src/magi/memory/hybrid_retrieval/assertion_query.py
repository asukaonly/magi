"""Host-owned assertion query vocabulary derived from projection semantics."""

from __future__ import annotations

from typing import Any

from ..l2.semantic_routing import assertion_predicate_descriptors
from .models import AssertionQuery


def assertion_query_catalog() -> dict[str, str]:
    """Describe selectable slots using the existing canonical predicates."""
    return {item.predicate: item.trait_code for item in assertion_predicate_descriptors()}


def parse_assertion_query(raw: Any) -> AssertionQuery | None:
    """Reject unsupported or malformed slot selections without widening them."""
    if not isinstance(raw, dict):
        return None
    predicates = raw.get("predicates")
    scope = raw.get("value_scope")
    catalog = assertion_query_catalog()
    if (
        not isinstance(predicates, list)
        or not predicates
        or not all(isinstance(predicate, str) and predicate in catalog for predicate in predicates)
        or not isinstance(scope, str)
        or scope not in {"any", "constrained"}
    ):
        return None
    return AssertionQuery(predicates=list(dict.fromkeys(predicates)), value_scope=scope)
