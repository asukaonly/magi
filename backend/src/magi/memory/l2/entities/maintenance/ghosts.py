"""Ghost entity reference cleanup facade for L2 entity maintenance."""

from __future__ import annotations

from .ghosts_common import (
    MAX_EVIDENCE_EVENT_IDS,
    _CatalogMaintenanceHostProtocol,
    _CatalogMaintenanceStatsProtocol,
    _canonical_entity_id,
    _merge_evidence_json,
)
from .ghosts_graph import L2EntityGhostGraphMaintenanceMixin
from .ghosts_tom import L2EntityTomGhostMaintenanceMixin


class L2EntityGhostMaintenanceMixin(
    L2EntityGhostGraphMaintenanceMixin,
    L2EntityTomGhostMaintenanceMixin,
):
    """Resolve ghost catalog IDs and rewrite affected graph/TOM rows."""


__all__ = [
    "MAX_EVIDENCE_EVENT_IDS",
    "L2EntityGhostMaintenanceMixin",
    "_CatalogMaintenanceHostProtocol",
    "_CatalogMaintenanceStatsProtocol",
    "_canonical_entity_id",
    "_merge_evidence_json",
]
