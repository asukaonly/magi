"""Connection-scoped, revocable host capability admission for plugin workers."""

from __future__ import annotations

import inspect
import threading
import time
from typing import Any, Callable

from magi_plugin_sdk.runtime import CapabilityGrant, InvocationIdentity, PluginConnection


class CapabilityDenied(PermissionError):
    """A worker requested authority outside a live host-issued grant."""


class CapabilityBroker:
    """Invoke explicitly registered host handlers under the original caller.

    A handler receives ``(identity, resource, payload)`` and must constrain any
    resource interpretation to the supplied, already authorized scope. No raw
    service object, registry or caller-selected connection crosses this API.
    """

    def __init__(
        self, connection: PluginConnection, grants: tuple[CapabilityGrant, ...] = ()
    ) -> None:
        self.connection = connection
        self._grants: dict[str, CapabilityGrant] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._lock = threading.RLock()
        self._closed = False
        for grant in grants:
            self.grant(grant)

    def grant(self, grant: CapabilityGrant) -> None:
        """Install a host-issued grant after contribution ownership is known."""
        grant = CapabilityGrant.model_validate(grant.model_dump(mode="json"))
        with self._lock:
            if self._closed:
                raise CapabilityDenied("Capability broker is closed")
            if grant.connection_id != self.connection.connection_id:
                raise CapabilityDenied("Capability grant belongs to another connection")
            if grant.grant_id in self._grants:
                raise ValueError("Capability grant is already registered")
            self._grants[grant.grant_id] = grant

    def register(self, capability: str, handler: Callable[..., Any]) -> None:
        with self._lock:
            if self._closed:
                raise CapabilityDenied("Capability broker is closed")
            if capability in self._handlers:
                raise ValueError("Capability handler already registered")
            self._handlers[capability] = handler

    def revoke(self, grant_id: str) -> None:
        with self._lock:
            self._grants.pop(grant_id, None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._grants.clear()

    def _admit(
        self, identity: InvocationIdentity, capability: str, resource: str
    ) -> Callable[..., Any]:
        with self._lock:
            if (
                self._closed
                or identity.connection_id != self.connection.connection_id
                or identity.plugin_id != self.connection.plugin_id
            ):
                raise CapabilityDenied("Invocation is outside this connection")
            handler = self._handlers.get(capability)
            if handler is None:
                raise CapabilityDenied("Host capability is unavailable")
            now = time.time()
            if not any(
                g.capability == capability
                and (g.expires_at is None or g.expires_at > now)
                and resource in g.scopes
                for g in self._grants.values()
            ):
                raise CapabilityDenied("Host capability scope is not granted")
            return handler

    async def invoke(
        self, identity: InvocationIdentity, capability: str, resource: str, payload: Any
    ) -> Any:
        handler = self._admit(identity, capability, resource)
        result = handler(identity, resource, payload)
        return await result if inspect.isawaitable(result) else result


def bind_source_services(
    broker: CapabilityBroker,
    *,
    get_connection: Callable[[str], PluginConnection],
    source_store: Any,
    emit_change: Callable[[dict[str, Any]], Any],
    source_types: frozenset[str],
) -> None:
    """Bind owned resources and source ingress without accepting worker authority.

    The caller supplies source types from registered sources, not projection
    selectors. Explicit grants are still required: source.emit scopes are source
    types; resources.create/read scopes are the host connection ID.
    """
    from magi_plugin_sdk.runtime import ResourceRef, SourceChange

    def connection_for(identity: InvocationIdentity) -> PluginConnection:
        connection = get_connection(identity.connection_id)
        if not connection.enabled or connection.plugin_id != identity.plugin_id:
            raise CapabilityDenied("Source connection is inactive")
        return connection

    async def emit(identity: InvocationIdentity, resource: str, payload: Any) -> Any:
        connection = connection_for(identity)
        if (
            resource not in source_types
            or not isinstance(payload, dict)
            or set(payload) != {"change"}
        ):
            raise CapabilityDenied("Source emission is outside its registered source")
        change = payload["change"]
        if not isinstance(change, SourceChange):
            change = SourceChange.model_validate(change)
        for reference in change.resources:
            if reference.connection_id != connection.connection_id:
                raise CapabilityDenied("Source resource belongs to another connection")
            if not await source_store.validate_operation_resource(identity, reference):
                raise CapabilityDenied("Source resource is not valid")
        # Connection authority is added here, never copied from plugin payload.
        envelope = {
            "source_type": resource,
            "connection_id": connection.connection_id,
            "source_change": change.model_dump(mode="json"),
        }
        result = emit_change(envelope)
        if inspect.isawaitable(result):
            await result
        # Scheduler objects remain host-owned; acknowledgement is plain data.
        return {"accepted": True}

    async def create(identity: InvocationIdentity, resource: str, payload: Any) -> ResourceRef:
        connection = connection_for(identity)
        if (
            resource != connection.connection_id
            or not isinstance(payload, dict)
            or not set(payload) <= {"content", "media_type", "display_name"}
        ):
            raise CapabilityDenied("Resource write is outside its connection")
        if not isinstance(payload.get("content"), bytes):
            raise ValueError("Resource content must be bytes")
        return await source_store.register_resource(
            connection,
            payload["content"],
            media_type=payload["media_type"],
            display_name=payload.get("display_name", ""),
        )

    async def read(identity: InvocationIdentity, resource: str, payload: Any) -> bytes:
        connection = connection_for(identity)
        reference = (
            payload if isinstance(payload, ResourceRef) else ResourceRef.model_validate(payload)
        )
        if (
            resource != connection.connection_id
            or reference.connection_id != connection.connection_id
        ):
            raise CapabilityDenied("Resource read is outside its connection")
        if reference.size_bytes > 2 * 1024 * 1024:
            raise ValueError("Resource exceeds the worker inline read limit")
        return await source_store.read_resource(connection, reference)

    broker.register("source.emit", emit)
    broker.register("resources.create", create)
    broker.register("resources.read", read)
