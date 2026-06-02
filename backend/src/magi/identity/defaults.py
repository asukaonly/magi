"""Canonical defaults for the identity layer.

``CANONICAL_LOCAL_USER`` is the magi-internal user id assumed by
single-user mode (the default deployment model today). Historically
this value lived as the bare string ``"local_user"`` in
``runtime_defaults.DEFAULT_USER_ID`` and again in
``user_profile/models.DEFAULT_USER_ID`` — duplicated. The identity
layer is now the single source of truth; those two modules re-export
from here so existing imports keep working.

The string value MUST NOT change without a migration script that
collapses all rows referencing the old value. ``"local_user"`` is
baked into 11 tables across 5 SQLite stores (see
``docs/identity-architecture.md`` §5.4).
"""
from __future__ import annotations

from .types import MagiUserID


# The single canonical MagiUserID for single-user mode. Wrapped via
# the ``MagiUserID`` NewType so type-checkers see it as the right
# type at call sites that have already opted into the ratchet.
CANONICAL_LOCAL_USER: MagiUserID = MagiUserID("local_user")


__all__ = ["CANONICAL_LOCAL_USER"]
