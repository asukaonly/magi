"""Host authorization for operation callers, connection grants and readiness."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from magi_plugin_sdk.runtime import (
    CapabilityGrant,
    CapabilityReadiness,
    ConnectionStatus,
    InvocationIdentity,
    OperationSpec,
    PluginConnection,
)

from ..config import get_config
from ..identity import CANONICAL_LOCAL_USER


def build_host_invocation(
    connection: PluginConnection,
    *,
    trigger: str,
    task_id: str | None = None,
    session_id: str | None = None,
    invocation_id: str | None = None,
) -> InvocationIdentity:
    """Mint the local host identity; public requests never supply a principal."""
    return InvocationIdentity(
        invocation_id=invocation_id or uuid.uuid4().hex,
        plugin_id=connection.plugin_id,
        connection_id=connection.connection_id,
        principal_id=str(CANONICAL_LOCAL_USER),
        trigger=trigger,
        task_id=task_id,
        session_id=session_id,
    )


class InstalledOperationAuthorizer:
    """Authorize against live installation, connection and consent state.

    Exact broker-owned scopes must be supplied from the composed broker's
    handler inventory. Native filesystem/network/subprocess scope claims are
    never inferred from a trusted worker's unrestricted operating-system access.
    """

    def __init__(
        self,
        *,
        get_package: Callable[[str], Any],
        connection_store: Any,
        get_connection_plugin: Callable[[str], Any] | None = None,
        config_provider: Callable[[], Any] = get_config,
        supported_host_scopes: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._package = get_package
        self._connections = connection_store
        owner = getattr(get_package, "__self__", None)
        self._plugin = get_connection_plugin or getattr(
            owner, "get_connection_plugin", None
        )
        self._readiness = (
            getattr(owner, "connection_readiness", None)
            or connection_store.get_readiness
        )
        self._config = config_provider
        self._supported_scopes = supported_host_scopes or {}

    def __call__(
        self,
        identity: InvocationIdentity,
        connection: PluginConnection,
        spec: OperationSpec,
        parameters: dict[str, Any],
    ) -> bool:
        if (
            identity.principal_id != str(CANONICAL_LOCAL_USER)
            or identity.trigger not in spec.triggers
        ):
            return False
        if (
            identity.connection_id != connection.connection_id
            or identity.plugin_id != connection.plugin_id
        ):
            return False
        required = self._consented_capabilities(connection, spec.required_capabilities)
        if (
            required is None
            or not connection.enabled
            or self._plugin is None
            or self._plugin(connection.connection_id) is None
        ):
            return False
        states = self._readiness(connection.connection_id)
        return any(
            item.capability_id == "connection" and item.status == ConnectionStatus.READY
            for item in states
        ) and all(
            readiness.status == ConnectionStatus.READY
            for readiness in states
            if readiness.capability_id in required | {spec.operation_id, "connection"}
        )

    def authorize_setup_connection(self, connection: PluginConnection) -> bool:
        """Authorize a disabled worker before import, without enabling contributions."""
        if connection.enabled or self._consented_capabilities(connection, ()) is None:
            return False
        manifest = self._package(connection.plugin_id).manifest
        return any(
            not item.requires_enabled for item in manifest.settings_actions
        ) or any(
            not getattr(item, "requires_enabled", True)
            for item in manifest.settings_resources
        )

    def authorize_setup(
        self,
        identity: InvocationIdentity,
        connection: PluginConnection,
        spec: OperationSpec,
        parameters: dict[str, Any],
    ) -> bool:
        """Admit only host-catalogued setup actions and presentation reads."""
        if (
            identity.principal_id != str(CANONICAL_LOCAL_USER)
            or identity.trigger != "user"
            or spec.triggers != ["user"]
            or identity.connection_id != connection.connection_id
            or identity.plugin_id != connection.plugin_id
            or not self.authorize_setup_connection(connection)
            or self._consented_capabilities(connection, spec.required_capabilities)
            is None
        ):
            return False
        manifest = self._package(connection.plugin_id).manifest
        for action in manifest.settings_actions:
            if not action.requires_enabled and spec.operation_id in {
                f"settings:{action.action_id}:{phase}"
                for phase in ("start", "poll", "cancel")
            }:
                return True
        return spec.effect == "read_only" and any(
            not getattr(resource, "requires_enabled", True)
            and spec.operation_id == f"settings-resource:{resource.resource_name}"
            for resource in manifest.settings_resources
        )

    def _consented_capabilities(
        self, connection: PluginConnection, capabilities: Iterable[str]
    ) -> set[str] | None:
        """Resolve live installation consent separately from scoped host callbacks."""
        try:
            current = self._connections.get(connection.connection_id)
        except KeyError:
            return None
        if current != connection:
            return None
        state = self._package(current.plugin_id)
        if state is None:
            return None
        configured = self._config().plugins.packages.get(current.plugin_id)
        if configured is None:
            return None
        manifest = state.manifest
        if manifest.source != "builtin" and (
            not state.trusted or not configured.trusted
        ):
            return None
        declarations = {item.capability: item for item in manifest.capabilities}
        consent = {
            item.capability: item for item in (configured.consented_capabilities or [])
        }
        required = set(capabilities)
        required.update(
            item.capability for item in declarations.values() if not item.optional
        )
        if manifest.source == "builtin":
            # Bundled host code is part of the application, not an external grant.
            return set() if not set(capabilities) else None
        if manifest.execution_mode not in {"trusted_process", "restricted_process"}:
            return None
        for capability in required:
            request, approved = declarations.get(capability), consent.get(capability)
            if request is None or approved is None:
                return None
            requested_scopes = set(request.scope)
            if not requested_scopes.issubset(set(approved.scope)):
                return None
            if manifest.execution_mode == "trusted_process":
                # Trusted workers intentionally retain the user's OS authority.
                # Installation consent is checked here; broker scopes govern
                # host callbacks separately and are not native confinement.
                continue
            if requested_scopes:
                if not requested_scopes.issubset(
                    self._supported_scopes.get(capability, frozenset())
                ):
                    return None
            elif capability in {
                "network",
                "filesystem_read",
                "filesystem_write",
                "subprocess",
            }:
                return None
        return required


class OperationAuthorizer:
    """Fail closed unless the current principal, connection and grants agree.

    Resolvers read host state, never operation arguments. Grant scopes are
    explicit operation selectors: ``operation:<id>`` or ``operation:*``.
    Principal resolution must cover the trigger's user or service identity.
    """

    def __init__(
        self,
        *,
        principal_allowed: Callable[[InvocationIdentity, PluginConnection], bool],
        grants_for_connection: Callable[[str], Iterable[CapabilityGrant]],
        readiness_for_connection: Callable[[str], Iterable[CapabilityReadiness]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._principal_allowed = principal_allowed
        self._grants = grants_for_connection
        self._readiness = readiness_for_connection
        self._clock = clock

    def __call__(
        self,
        identity: InvocationIdentity,
        connection: PluginConnection,
        spec: OperationSpec,
        parameters: dict[str, Any],
    ) -> bool:
        """Check fresh host policy for each final, post-hook invocation."""
        if (
            not connection.enabled
            or identity.connection_id != connection.connection_id
            or identity.plugin_id != connection.plugin_id
        ):
            return False
        if (
            identity.trigger not in spec.triggers
            or self._principal_allowed(identity, connection) is not True
        ):
            return False
        readiness = {
            item.capability_id: item
            for item in self._readiness(connection.connection_id)
            if item.connection_id == connection.connection_id
        }
        operation_state = readiness.get(spec.operation_id)
        if (
            operation_state is not None
            and operation_state.status != ConnectionStatus.READY
        ):
            return False
        grants = tuple(self._grants(connection.connection_id))
        now = self._clock()
        for capability in spec.required_capabilities:
            state = readiness.get(capability)
            if state is None or state.status != ConnectionStatus.READY:
                return False
            if not any(
                grant.connection_id == connection.connection_id
                and grant.capability == capability
                and (grant.expires_at is None or grant.expires_at > now)
                and (
                    f"operation:{spec.operation_id}" in grant.scopes
                    or "operation:*" in grant.scopes
                )
                for grant in grants
            ):
                return False
        return True


__all__ = [
    "OperationAuthorizer",
    "InstalledOperationAuthorizer",
    "build_host_invocation",
]
