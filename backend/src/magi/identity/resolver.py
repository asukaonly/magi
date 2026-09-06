"""Identity resolver — the public service surface of the identity layer.

Two concrete implementations share one ``IdentityResolver`` Protocol:

  * ``LocalUserResolver`` — single-user mode (today's default). Every
    external identity collapses to ``CANONICAL_LOCAL_USER``. Bindings
    are recorded for forensics but never consulted for resolution.
  * ``BindingTableResolver`` — multi-user mode (future). Reads the
    bindings table; unbound external identities auto-bind to
    ``CANONICAL_LOCAL_USER`` (preserves single-user-default semantics
    until an explicit rebind via a yet-to-build UI).

Bootstrap picks one based on config; all upper-layer callers see one
interface.

See ``docs/identity-architecture.md`` §6 for the design rationale.
"""
from __future__ import annotations

from typing import Protocol

from ..core.logger import get_logger
from .bindings_store import IdentityBindingsStore
from .defaults import CANONICAL_LOCAL_USER
from .types import ExternalIdentity, MagiUserID

logger = get_logger(__name__)


class IdentityResolver(Protocol):
    """Resolve external identifiers to canonical ``MagiUserID``.

    Every ingress site (channels dispatcher, api dispatch, source_hub,
    session_mapper) calls ``resolve()`` to canonicalize the inbound
    user identity before the value flows to any downstream store.
    """

    async def resolve(self, external: ExternalIdentity) -> MagiUserID:
        """Return the canonical ``MagiUserID`` for the given external
        identity. Always succeeds — unbound identities auto-bind to
        the canonical local user in single-user mode, and to whatever
        the binding policy says in multi-user mode."""
        ...

    async def bind(
        self,
        external: ExternalIdentity,
        magi_user_id: MagiUserID,
    ) -> None:
        """Explicitly bind an external identity to a specific
        ``MagiUserID``. Used by the future "connect another account"
        UI; not called on the hot path."""
        ...

    async def lookup_externals(
        self,
        magi_user_id: MagiUserID,
    ) -> list[ExternalIdentity]:
        """Return all external identities bound to this ``MagiUserID``.
        Used by the "connected accounts" UI."""
        ...

    def canonical_local(self) -> MagiUserID:
        """Return the canonical local-user id. Always safe to call;
        does not touch I/O. Useful for callers that need the canonical
        default at construction time (e.g. defaults for HTTP form
        params)."""
        ...


class LocalUserResolver:
    """Single-user mode resolver.

    Every ``resolve()`` returns ``CANONICAL_LOCAL_USER`` regardless of
    the external identity. The binding gets recorded (so the
    "connected accounts" forensic view works) but does NOT affect
    resolution: even if a row in ``user_identity_bindings`` says
    ``magi_user_id = "alice"``, this resolver still returns
    ``CANONICAL_LOCAL_USER``. That's the contract — switching to
    multi-user is a config flip to ``BindingTableResolver``, not a
    behavior change of this class.
    """

    def __init__(self, *, bindings_store: IdentityBindingsStore) -> None:
        self._bindings = bindings_store

    async def resolve(self, external: ExternalIdentity) -> MagiUserID:
        # Record the binding for forensics (idempotent — bind() handles
        # repeat calls). Swallow store errors: identity resolution must
        # never break inbound processing.
        try:
            await self._bindings.bind(external, CANONICAL_LOCAL_USER)
        except Exception as exc:
            logger.warning(
                "LocalUserResolver: bindings_store.bind failed "
                "channel_type=%s external_user_id=%s error=%s",
                external.channel_type, external.external_user_id, exc,
            )
        return CANONICAL_LOCAL_USER

    async def bind(
        self,
        external: ExternalIdentity,
        magi_user_id: MagiUserID,
    ) -> None:
        # The store accepts the bind, but in single-user mode the
        # resolution policy ignores it. Logged at debug so ops can
        # see a no-op rebind attempt.
        await self._bindings.bind(external, magi_user_id)
        if magi_user_id != CANONICAL_LOCAL_USER:
            logger.debug(
                "LocalUserResolver.bind recorded non-canonical magi_user_id=%r; "
                "resolve() will still return CANONICAL_LOCAL_USER. Switch to "
                "BindingTableResolver to honor multi-user bindings.",
                magi_user_id,
            )

    async def lookup_externals(
        self,
        magi_user_id: MagiUserID,
    ) -> list[ExternalIdentity]:
        return await self._bindings.lookup_externals(magi_user_id)

    def canonical_local(self) -> MagiUserID:
        return CANONICAL_LOCAL_USER


class BindingTableResolver:
    """Multi-user mode resolver (Phase 2+; not currently wired).

    ``resolve()`` queries the bindings table. Unbound external
    identities auto-bind to ``CANONICAL_LOCAL_USER`` to preserve
    single-user-default behavior — a brand-new external account
    immediately lands in the local user's namespace, exactly as
    ``LocalUserResolver`` would do. The difference shows up only
    once a user explicitly rebinds via UI.
    """

    def __init__(self, *, bindings_store: IdentityBindingsStore) -> None:
        self._bindings = bindings_store

    async def resolve(self, external: ExternalIdentity) -> MagiUserID:
        existing = await self._bindings.lookup(external)
        if existing is not None:
            return existing.magi_user_id
        # First-time bind: auto-bind to canonical local user. The
        # multi-user UI is the only path that produces a non-local
        # binding (via ``bind()``).
        binding = await self._bindings.bind(external, CANONICAL_LOCAL_USER)
        return binding.magi_user_id

    async def bind(
        self,
        external: ExternalIdentity,
        magi_user_id: MagiUserID,
    ) -> None:
        await self._bindings.bind(external, magi_user_id)

    async def lookup_externals(
        self,
        magi_user_id: MagiUserID,
    ) -> list[ExternalIdentity]:
        return await self._bindings.lookup_externals(magi_user_id)

    def canonical_local(self) -> MagiUserID:
        return CANONICAL_LOCAL_USER


__all__ = ["IdentityResolver", "LocalUserResolver", "BindingTableResolver"]
