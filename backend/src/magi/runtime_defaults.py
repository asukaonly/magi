"""Shared runtime defaults for the desktop-first application.

``DEFAULT_USER_ID`` is re-exported from ``magi.identity.defaults.CANONICAL_LOCAL_USER``
so the value is declared once (the identity layer is the canonical
authority for user-id semantics; see ``docs/identity-architecture.md``).
Type-wise it's ``MagiUserID``, a ``NewType[str]`` — runtime-equal to
plain ``"local_user"`` but type-checker-distinct, which primes the
future Phase 3 ratchet without breaking any existing ``str``-typed
caller (NewType assigns to its underlying type freely).
"""

from .identity.defaults import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

DEFAULT_RUNTIME_NAMESPACE = "desktop"

__all__ = ["DEFAULT_USER_ID", "DEFAULT_RUNTIME_NAMESPACE"]
