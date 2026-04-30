"""Snapshot evolution and reconciliation helpers for the L2 cognition store."""

from __future__ import annotations

from .reconcile_state import L2ReconcileStateMixin, _MOMENTARY_TRAITS
from .snapshot_evolution import L2SnapshotEvolutionMixin, _SNAPSHOT_HISTORY_LIMIT


class L2StoreReconcileMixin(
    L2SnapshotEvolutionMixin,
    L2ReconcileStateMixin,
):
    """Compose L2 snapshot evolution and assertion reconcile helpers."""


__all__ = [
    "L2StoreReconcileMixin",
    "L2SnapshotEvolutionMixin",
    "L2ReconcileStateMixin",
    "_MOMENTARY_TRAITS",
    "_SNAPSHOT_HISTORY_LIMIT",
]
