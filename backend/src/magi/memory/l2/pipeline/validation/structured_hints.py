"""Structured hint helpers for the L2 cognition pipeline."""

from __future__ import annotations

from .structured_entity_hints import L2StructuredEntityHintMixin
from .structured_facet_hints import L2StructuredFacetHintMixin
from .structured_graph_hints import L2StructuredGraphHintMixin
from .structured_hint_common import (
    L2StructuredHintHostMixin,
    _L2StructuredHintHostProtocol,
    _STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS,
    _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES,
    _STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS,
)


class L2StructuredHintMixin(
    L2StructuredEntityHintMixin,
    L2StructuredGraphHintMixin,
    L2StructuredFacetHintMixin,
    L2StructuredHintHostMixin,
):
    """Own deterministic structured entity, graph, and facet hint conversion."""


__all__ = [
    "L2StructuredHintMixin",
    "L2StructuredHintHostMixin",
    "_L2StructuredHintHostProtocol",
    "_STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS",
    "_STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES",
    "_STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS",
]
