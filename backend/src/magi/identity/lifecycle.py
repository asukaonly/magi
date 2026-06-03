"""Lifecycle module for the identity layer.

Initializes the ``IdentityBindingsStore`` and constructs the active
``IdentityResolver`` implementation, parking both on the bootstrap
context's ``identity`` slice so the four ingress sites can pull them
during their own init.

Lifecycle ordering: identity sits in the infrastructure phase right
after ``CoreDependenciesModule`` (which provides ``runtime_paths``).
It is itself a dependency of any module that touches user identity
on the inbound path — channels, awareness, agent runtime — though
those modules pick the resolver up via the bootstrap context rather
than via a hard dependency edge, since identity is L1 substrate.

Today the resolver is always ``LocalUserResolver`` (single-user
mode). When multi-user lands, this module becomes the seam where
the config picks ``BindingTableResolver`` instead.
"""
from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .bindings_store import IdentityBindingsStore
from .resolver import IdentityResolver, LocalUserResolver

logger = get_logger(__name__)


class IdentityModule(LifecycleModule):
    """Initialize the identity bindings store and resolver."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_identity",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context
        self._store: IdentityBindingsStore | None = None
        self._resolver: IdentityResolver | None = None

    async def init(self) -> None:
        runtime_paths = require_initialized(
            self._context.core.runtime_paths, "runtime paths"
        )
        db_path = str(runtime_paths.identity_db_path)
        store = IdentityBindingsStore(db_path=db_path)
        await store.initialize()
        resolver = LocalUserResolver(bindings_store=store)
        self._store = store
        self._resolver = resolver
        self._context.identity.store = store
        self._context.identity.resolver = resolver
        self._context.identity.module = self
        logger.info(
            "Identity module initialized db=%s resolver=%s",
            db_path, type(resolver).__name__,
        )

    async def shutdown(self) -> None:
        self._context.identity.module = None
        self._context.identity.resolver = None
        self._context.identity.store = None
        self._store = None
        self._resolver = None

    @property
    def resolver(self) -> IdentityResolver | None:
        return self._resolver

    @property
    def store(self) -> IdentityBindingsStore | None:
        return self._store


__all__ = ["IdentityModule"]
