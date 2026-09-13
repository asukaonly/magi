"""Connection-owned ingress registrations and in-flight lifecycle leases."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock

from magi_plugin_sdk.ingress import (  # noqa: F401
    PluginIngressEventHandler,
    PluginIngressEventRecord,
    PluginIngressHandlerRegistration,
)


@dataclass
class _Owner:
    epoch: str
    entries: dict[tuple[str, str], PluginIngressHandlerRegistration]
    active: int = 0
    closed: bool = False
    drained: Future[None] = field(default_factory=Future)


class PluginIngressRegistry:
    """Detach synchronously, then drain leases before shutting down a plugin worker."""

    def __init__(self) -> None:
        self.ready = False
        self._owners: dict[str, _Owner] = {}
        self._retired: dict[str, _Owner] = {}
        self._lock = RLock()

    def register(
        self, connection_id: str, epoch: str,
        registrations: list[PluginIngressHandlerRegistration],
    ) -> Callable[[], None]:
        entries = {(entry.plugin_target, entry.event_type): entry for entry in registrations}
        if len(entries) != len(registrations):
            raise ValueError("Duplicate ingress registration within a connection")
        owner = _Owner(epoch, entries)
        with self._lock:
            if connection_id in self._owners or connection_id in self._retired:
                raise ValueError("Previous ingress owner has not been drained")
            self._owners[connection_id] = owner

        def dispose() -> None:
            with self._lock:
                if self._owners.get(connection_id) is not owner:
                    return
                del self._owners[connection_id]
                owner.closed = True
                self._retired[connection_id] = owner
                if owner.active == 0:
                    owner.drained.set_result(None)

        return dispose

    def connection_active(self, connection_id: str) -> bool:
        with self._lock:
            return connection_id in self._owners

    @contextmanager
    def lease(
        self, connection_id: str, epoch: str, target: str, event_type: str,
    ) -> Iterator[PluginIngressHandlerRegistration | None]:
        with self._lock:
            owner = self._owners.get(connection_id)
            entry = owner.entries.get((target, event_type)) if owner and owner.epoch == epoch else None
            if entry is not None:
                owner.active += 1
        try:
            yield entry
        finally:
            if entry is not None:
                with self._lock:
                    owner.active -= 1
                    if owner.closed and owner.active == 0:
                        owner.drained.set_result(None)

    async def drain(self, connection_id: str) -> None:
        with self._lock:
            owner = self._retired.get(connection_id)
        if owner is None:
            return
        await asyncio.shield(asyncio.wrap_future(owner.drained))
        with self._lock:
            if self._retired.get(connection_id) is owner:
                del self._retired[connection_id]
