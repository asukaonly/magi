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


def canonicalize_user_id(raw: str | None) -> MagiUserID:
    """Coerce a raw user-id string into a canonical ``MagiUserID``.

    Belt-and-suspenders for ingress sites that receive a ``user_id``
    string from outside the identity layer (HTTP form arg, message-bus
    event payload, plugin-supplied dict, etc.). The proper flow goes
    through ``IdentityResolver.resolve(ExternalIdentity)``; this helper
    is the synchronous defense for sites that don't have an
    ``ExternalIdentity`` because they already lost the channel-type
    context.

    Today (single-user mode):

    * Empty / None → ``CANONICAL_LOCAL_USER`` (matches the historical
      ``DEFAULT_USER_ID`` fallback).
    * Channel-prefixed (``channel_*``) → ``CANONICAL_LOCAL_USER``
      (the same collapse the L2 entity helper has been doing locally
      for a while; centralizing it here means the helper there
      becomes defensive-only).
    * Anything else → wrapped as-is in ``MagiUserID`` (single-user
      mode honors whatever the caller specified, but type-checkers
      now see it as MagiUserID so downstream signatures are happy).

    When multi-user mode lands, this helper either disappears
    (callers go through the resolver) or grows a binding lookup.
    Either way the call sites stay the same.
    """
    if raw is None:
        return CANONICAL_LOCAL_USER
    stripped = raw.strip()
    if not stripped:
        return CANONICAL_LOCAL_USER
    if stripped.startswith("channel_"):
        return CANONICAL_LOCAL_USER
    return MagiUserID(stripped)


__all__ = ["CANONICAL_LOCAL_USER", "canonicalize_user_id"]
