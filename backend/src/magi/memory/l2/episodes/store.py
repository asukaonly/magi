"""Episode persistence mixin facade for the L2 cognition store."""

from __future__ import annotations

from .crud import L2EpisodeCrudMixin
from .fts import L2EpisodeFtsMixin
from .memberships import L2EpisodeMembershipMixin


class L2EpisodeStoreMixin(
    L2EpisodeCrudMixin,
    L2EpisodeMembershipMixin,
    L2EpisodeFtsMixin,
):
    """CRUD, membership, and FTS helpers for L2 episodes."""


__all__ = ["L2EpisodeStoreMixin"]
