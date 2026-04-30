"""Compatibility facade for L2 cognition store retrieval queries."""

from __future__ import annotations

from .assertions import L2StoreAssertionQueryMixin
from .relationships import L2StoreRelationshipQueryMixin
from .snapshots import L2StoreSnapshotQueryMixin


class L2StoreQueryMixin(
    L2StoreAssertionQueryMixin,
    L2StoreSnapshotQueryMixin,
    L2StoreRelationshipQueryMixin,
):
    """Compose assertion, snapshot, and relationship retrieval helpers."""


__all__ = ["L2StoreQueryMixin"]
