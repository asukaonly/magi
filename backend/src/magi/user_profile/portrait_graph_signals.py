"""Shared extraction of safe L2 graph relationships into portrait world clues.

Both the materialized portrait projection (``UserPortraitProjectionBuilder``)
and the API fallback path consume this module so visited places, owned/used
tools, and similar graph clues are admitted, cleaned, and deduped through one
implementation instead of diverging per call site.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from ..memory.l2.entities.catalog.lookup import get_canonical_names
from .portrait_signal_policy import (
    PORTRAIT_GRAPH_WORLD_RULES,
    graph_relation_portrait_world_group,
)

logger = logging.getLogger(__name__)

_GRAPH_SIGNAL_LIMIT = 12
_GRAPH_QUERY_LIMIT = 80
_LOW_VALUE_GRAPH_NAME_RE = re.compile(r"[0-9a-f]{10,}", re.IGNORECASE)
_COORDINATE_GRAPH_NAME_RE = re.compile(
    r"[-+]?\d{1,3}(?:\.\d+)?\s*,\s*[-+]?\d{1,3}(?:\.\d+)?"
)


@dataclass(frozen=True)
class PortraitGraphSignal:
    """A safe graph relationship promoted to a portrait world clue."""

    world_group: str
    text: str
    observation_count: int
    source_type: str
    predicate: str
    object_type: str
    triple_id: str


async def collect_portrait_graph_signals(
    l2: Any,
    *,
    entity_id: str,
    limit: int = _GRAPH_SIGNAL_LIMIT,
) -> list[PortraitGraphSignal]:
    """Return deduped portrait world clues derived from L2 graph relationships.

    Resilient to a store without ``get_relationships`` or a non-awaiting stub,
    in which case an empty list is returned so callers degrade gracefully.
    """
    getter = getattr(l2, "get_relationships", None)
    if not callable(getter):
        return []

    result = getter(
        subject_id=entity_id,
        predicates=list(PORTRAIT_GRAPH_WORLD_RULES),
        status="active",
        limit=_GRAPH_QUERY_LIMIT,
    )
    if not isawaitable(result):
        return []
    relationships = await result
    if not isinstance(relationships, list) or not relationships:
        return []

    canonical_names = await _resolve_canonical_names(l2, relationships)

    signals: list[PortraitGraphSignal] = []
    seen: set[tuple[str, str]] = set()
    for edge in relationships:
        if not isinstance(edge, dict):
            continue
        signal = _signal_from_edge(edge, canonical_names)
        if signal is None:
            continue
        key = (signal.world_group, signal.text.casefold())
        if key in seen:
            continue
        seen.add(key)
        signals.append(signal)
        if len(signals) >= limit:
            break
    return signals


async def _resolve_canonical_names(
    l2: Any,
    relationships: list[Any],
) -> dict[str, str]:
    object_ids = [
        str(edge.get("object_id") or "").strip()
        for edge in relationships
        if isinstance(edge, dict) and str(edge.get("object_id") or "").strip()
    ]
    db_path = getattr(l2, "db_path", None)
    if not (isinstance(db_path, str) and db_path.strip() and object_ids):
        return {}
    try:
        return await get_canonical_names(db_path, object_ids)
    except Exception as exc:  # noqa: BLE001 - canonical name lookup is best-effort
        logger.debug("portrait graph: canonical name lookup failed: %s", exc)
        return {}


def _signal_from_edge(
    edge: dict[str, Any],
    canonical_names: dict[str, str],
) -> PortraitGraphSignal | None:
    predicate = str(edge.get("predicate") or "").strip().upper()
    object_type = str(edge.get("object_type") or "").strip().casefold()
    world_group = graph_relation_portrait_world_group(
        predicate=predicate,
        object_type=object_type,
        observation_count=int(edge.get("observation_count", 0) or 0),
    )
    if world_group is None:
        return None

    text = _graph_object_name(edge=edge, canonical_names=canonical_names)
    if not text:
        return None

    return PortraitGraphSignal(
        world_group=world_group,
        text=text,
        observation_count=int(edge.get("observation_count") or 1),
        source_type=str(edge.get("source_type") or "").strip(),
        predicate=predicate,
        object_type=object_type,
        triple_id=str(edge.get("triple_id") or "").strip(),
    )


def _graph_object_name(
    *,
    edge: dict[str, Any],
    canonical_names: dict[str, str],
) -> str:
    object_id = str(edge.get("object_id") or "").strip()
    raw_name = canonical_names.get(object_id, "") if object_id else ""
    if not raw_name:
        raw_name = _object_slug(object_id)
    name = raw_name.replace("_", " ").strip()
    if not name:
        return ""
    if _LOW_VALUE_GRAPH_NAME_RE.fullmatch(name):
        return ""
    if _COORDINATE_GRAPH_NAME_RE.fullmatch(name):
        return ""
    return name[:80]


def _object_slug(object_id: str) -> str:
    if ":" in object_id:
        return object_id.split(":", 1)[1]
    return object_id


__all__ = ["PortraitGraphSignal", "collect_portrait_graph_signals"]
