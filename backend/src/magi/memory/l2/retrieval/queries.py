"""Compose L2 cognition store retrieval queries."""

from __future__ import annotations

from .assertions import L2StoreAssertionQueryMixin
from .relationships import L2StoreRelationshipQueryMixin
from .snapshots import L2StoreSnapshotQueryMixin
from .shadow_conflicts import L2StoreShadowConflictQueryMixin


class L2StoreQueryMixin(
    L2StoreAssertionQueryMixin,
    L2StoreSnapshotQueryMixin,
    L2StoreRelationshipQueryMixin,
    L2StoreShadowConflictQueryMixin,
):
    """Compose assertion, snapshot, and relationship retrieval helpers."""


__all__ = ["L2StoreQueryMixin"]
