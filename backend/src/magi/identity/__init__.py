"""Identity layer — canonical user-identifier authority.

L1 substrate (sibling of ``core/``, ``scheduler/``, ``runtime_trace/``).
Every upper layer imports from here when it needs to know "which
canonical user is this event for". External identifiers (WeChat
OpenID, Telegram chat_id, etc.) must NOT flow past the four ingress
boundaries defined in ``docs/identity-architecture.md`` §6.5 — they
get resolved into ``MagiUserID`` at the boundary and the boundary
alone.
"""
from __future__ import annotations

from .bindings_store import IdentityBinding, IdentityBindingsStore
from .defaults import CANONICAL_LOCAL_USER
from .resolver import BindingTableResolver, IdentityResolver, LocalUserResolver
from .types import ExternalIdentity, MagiUserID


__all__ = [
    "CANONICAL_LOCAL_USER",
    "BindingTableResolver",
    "ExternalIdentity",
    "IdentityBinding",
    "IdentityBindingsStore",
    "IdentityResolver",
    "LocalUserResolver",
    "MagiUserID",
]
