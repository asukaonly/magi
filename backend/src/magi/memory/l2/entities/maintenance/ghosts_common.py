"""Shared helpers for L2 ghost entity maintenance."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Protocol

from ...storage.utils import MAX_EVIDENCE_EVENT_IDS, max_evidence_event_ids


def _slugify_entity_id_suffix(value: str) -> str:
    """Match L2Pipeline._slugify for stable entity_id suffix comparison."""
    normalized = value.strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if slug:
        return slug
    return uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12]


def _canonical_entity_id(entity_type: str, canonical_name: str) -> str:
    return f"{entity_type}:{_slugify_entity_id_suffix(canonical_name)}"


def _merge_evidence_json(a: str, b: str, *, max_items: int | None = None) -> str:
    cap = max_items if max_items is not None else max_evidence_event_ids()
    try:
        la = json.loads(a or "[]")
        lb = json.loads(b or "[]")
    except json.JSONDecodeError:
        return a or b or "[]"
    if not isinstance(la, list):
        la = []
    if not isinstance(lb, list):
        lb = []
    seen: set[str] = set()
    out: list[Any] = []
    for item in la + lb:
        s = str(item)
        if s not in seen:
            seen.add(s)
            out.append(item)
    if len(out) > cap:
        out = out[-cap:]
    return json.dumps(out)


class _CatalogMaintenanceStatsProtocol(Protocol):
    ghost_edges_rewritten: int
    ghost_rows_merged: int
    ghost_skipped_no_target: int
    tom_entity_refs_rewritten: int
    fragment_entities_merged: int
    fragment_groups_processed: int
    orphans_pruned: int
    snapshots_refreshed: int
    errors: list[str]


class _CatalogMaintenanceHostProtocol(Protocol):
    _db_path: str


class L2EntityGhostHostMixin:
    """Provide the shared catalog-maintenance host cast."""

    def _catalog_maintenance_host(self) -> _CatalogMaintenanceHostProtocol:
        return self  # type: ignore[return-value]


__all__ = [
    "MAX_EVIDENCE_EVENT_IDS",
    "L2EntityGhostHostMixin",
    "_CatalogMaintenanceHostProtocol",
    "_CatalogMaintenanceStatsProtocol",
    "_canonical_entity_id",
    "_merge_evidence_json",
    "_slugify_entity_id_suffix",
]
