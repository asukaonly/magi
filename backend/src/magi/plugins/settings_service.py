"""Plugin settings resources and actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
from typing import Any

from .base import Plugin
from magi_plugin_sdk.runtime import (
    InvocationIdentity,
    OperationResult,
    OperationSpec,
    PluginConnection,
)
from magi_plugin_sdk.tools import ToolExecutionContext
from .operations import PluginOperationRegistry
from .operation_authorization import build_host_invocation
from ..identity import CANONICAL_LOCAL_USER
from .operation_execution import (
    plugin_runtime_operation,
    run_plugin_callback_operation,
    run_plugin_lifecycle_operation,
)
from .contracts import (
    ContributionType,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourcePayload,
    PluginSettingsResourceSpec,
)


@dataclass(frozen=True)
class PluginSettingsActionRun:
    """Host-owned envelope for one plugin settings action session response."""

    session_id: str
    result: PluginSettingsActionResult


def collect_plugin_settings_actions(
    plugin_instance: Plugin,
) -> list[PluginSettingsActionSpec]:
    actions: list[PluginSettingsActionSpec] = []
    for raw_action in plugin_instance.get_settings_actions():
        if isinstance(raw_action, PluginSettingsActionSpec):
            actions.append(raw_action)
        else:
            actions.append(PluginSettingsActionSpec.model_validate(raw_action))
    return actions


def settings_actions_for_contribution(
    actions: list[PluginSettingsActionSpec],
    *,
    contribution_id: str,
    contribution_type: ContributionType,
    surface: str,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for action in actions:
        if action.surface != surface:
            continue
        if action.contribution_id:
            if action.contribution_id != contribution_id:
                continue
        elif action.contribution_type != contribution_type:
            continue
        matched.append(action.model_dump(mode="json"))
    return sorted(matched, key=lambda item: int(item.get("order") or 0))


class PluginSettingsService:
    """Normalize connection settings actions through the operation runtime."""

    def __init__(
        self,
        *,
        get_connection: Callable[[str], PluginConnection],
        get_connection_plugin: Callable[[str], Plugin | None],
        operation_registry: PluginOperationRegistry,
        update_connection_settings: Callable[[str, dict[str, Any], int], Any],
        get_package: Callable[[str], Any] | None = None,
        get_setup_plugin: Callable[[str], Plugin | None] | None = None,
    ) -> None:
        self._get_connection = get_connection
        self._get_connection_plugin = get_connection_plugin
        self._operations = operation_registry
        self._update_connection_settings = update_connection_settings
        self._get_package = get_package
        self._get_setup_plugin = get_setup_plugin
        self._registrations: dict[
            tuple[str, str], tuple[Plugin, list[Callable[[], None]]]
        ] = {}
        self._sessions: dict[tuple[str, str, str], str] = {}

    async def read_plugin_settings_resource(
        self, connection_id: str, resource_name: str
    ) -> PluginSettingsResourcePayload:
        """Read an authorized host-catalogued resource through the shared runtime."""
        async with plugin_runtime_operation():
            connection, plugin, spec = await run_plugin_callback_operation(
                lambda: self._resolve_settings(connection_id, "resource", resource_name)
            )
            self._register_resource(connection, plugin, spec)
            result = await self._operations.invoke(
                connection_id,
                f"settings-resource:{resource_name}",
                {},
                identity=build_host_invocation(connection, trigger="user"),
            )
            if result.status != "succeeded":
                if result.error_code == "PERMISSION_DENIED":
                    raise PermissionError("Settings resource is not authorized")
                raise RuntimeError("Settings resource could not be read")
            return PluginSettingsResourcePayload(
                plugin_id=connection.plugin_id,
                resource_name=resource_name,
                resource_type=spec.resource_type,
                data=result.value,
            )

    async def start_plugin_settings_action(
        self,
        connection_id: str,
        action_id: str,
        *,
        identity: InvocationIdentity,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        """Start an action once, using the host invocation ID as session identity."""
        session_id = identity.invocation_id
        key = (connection_id, action_id, session_id)
        if key in self._sessions:
            raise ValueError("Settings action session already exists")
        result = await self._run(
            connection_id,
            action_id,
            "start",
            identity=identity,
            session_id=session_id,
            field_values=field_values,
        )
        if result.status not in {"failed", "cancelled"}:
            self._sessions[key] = identity.principal_id
        return PluginSettingsActionRun(session_id=session_id, result=result)

    async def poll_plugin_settings_action(
        self,
        connection_id: str,
        action_id: str,
        *,
        identity: InvocationIdentity,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        """Poll only a session owned by the same connection and caller."""
        self._require_session(connection_id, action_id, session_id, identity)
        result = await self._run(
            connection_id,
            action_id,
            "poll",
            identity=identity,
            session_id=session_id,
            field_values=field_values,
        )
        if result.status != "pending":
            self._sessions.pop((connection_id, action_id, session_id), None)
        return PluginSettingsActionRun(session_id=session_id, result=result)

    async def cancel_plugin_settings_action(
        self,
        connection_id: str,
        action_id: str,
        *,
        identity: InvocationIdentity,
        session_id: str,
    ) -> PluginSettingsActionRun:
        """Request cancellation through the same governed operation path."""
        self._require_session(connection_id, action_id, session_id, identity)
        result = await self._run(
            connection_id,
            action_id,
            "cancel",
            identity=identity,
            session_id=session_id,
            field_values=None,
        )
        self._sessions.pop((connection_id, action_id, session_id), None)
        return PluginSettingsActionRun(session_id=session_id, result=result)

    def unregister_connection(self, connection_id: str) -> None:
        """Revoke loaded callbacks and session ownership on unload or clear."""
        for key in [key for key in self._registrations if key[0] == connection_id]:
            _, disposers = self._registrations.pop(key)
            for dispose in reversed(disposers):
                dispose()
        self._sessions = {
            key: owner
            for key, owner in self._sessions.items()
            if key[0] != connection_id
        }

    def _resolve_settings(
        self, connection_id: str, kind: str, name: str
    ) -> tuple[PluginConnection, Plugin, Any]:
        """Resolve manifest declarations before starting any disabled worker."""
        connection = self._get_connection(connection_id)
        package = self._get_package(connection.plugin_id) if self._get_package else None
        if package is None:
            raise PermissionError("Settings require an installed host catalog")
        manifest = package.manifest
        entries = (
            manifest.settings_actions
            if kind == "action"
            else manifest.settings_resources
        )
        plugin = (
            self._get_connection_plugin(connection_id) if connection.enabled else None
        )
        if manifest.source == "builtin" and plugin is not None:
            entries = (
                plugin.get_settings_actions()
                if kind == "action"
                else plugin.get_settings_resources()
            )
        model = (
            PluginSettingsActionSpec if kind == "action" else PluginSettingsResourceSpec
        )
        entries = [model.model_validate(item) for item in entries]
        field = "action_id" if kind == "action" else "resource_name"
        spec = next((item for item in entries if getattr(item, field) == name), None)
        if spec is None:
            raise KeyError(name)
        if not connection.enabled:
            if (
                getattr(spec, "requires_enabled", True)
                or self._get_setup_plugin is None
            ):
                raise PermissionError(
                    "This settings entry requires an enabled connection"
                )
            plugin = self._get_setup_plugin(connection_id)
        if plugin is None:
            raise RuntimeError("Settings connection is not loaded")
        return connection, plugin, spec

    def _require_session(
        self,
        connection_id: str,
        action_id: str,
        session_id: str,
        identity: InvocationIdentity,
    ) -> None:
        if (
            self._sessions.get((connection_id, action_id, session_id))
            != identity.principal_id
        ):
            raise PermissionError(
                "Settings action session does not belong to this caller"
            )

    async def _run(
        self,
        connection_id: str,
        action_id: str,
        phase: str,
        *,
        identity: InvocationIdentity,
        session_id: str,
        field_values: dict[str, Any] | None,
    ) -> PluginSettingsActionResult:
        async with plugin_runtime_operation():
            connection = self._get_connection(connection_id)
            if (
                identity.connection_id != connection_id
                or identity.plugin_id != connection.plugin_id
                or identity.trigger != "user"
                or identity.principal_id != str(CANONICAL_LOCAL_USER)
            ):
                raise PermissionError(
                    "Settings action requires the matching host user invocation"
                )
            connection, plugin, spec = await run_plugin_callback_operation(
                lambda: self._resolve_settings(connection_id, "action", action_id)
            )
            self._register_action(connection, plugin, spec)
            result = await self._operations.invoke(
                connection_id,
                f"settings:{action_id}:{phase}",
                {"session_id": session_id, "field_values": dict(field_values or {})},
                identity=identity,
            )
            if result.status != "succeeded":
                return PluginSettingsActionResult(
                    status=result.status,
                    message=result.message
                    or result.error_code
                    or "Settings operation failed",
                )
            action_result = PluginSettingsActionResult.model_validate(result.value)
            if (
                action_result.status == "succeeded"
                and spec.persist_settings_on_success
                and action_result.settings_updates
            ):
                current = self._get_connection(connection_id)
                await run_plugin_lifecycle_operation(
                    lambda: self._update_connection_settings(
                        connection_id,
                        {**current.settings, **action_result.settings_updates},
                        current.revision,
                    )
                )
            return action_result

    def _register_action(
        self,
        connection: PluginConnection,
        plugin: Plugin,
        spec: PluginSettingsActionSpec,
    ) -> None:
        key = (connection.connection_id, spec.action_id)
        previous = self._registrations.get(key)
        if previous is not None and previous[0] is plugin:
            return
        if previous is not None:
            for dispose in reversed(previous[1]):
                dispose()
        disposers: list[Callable[[], None]] = []
        try:
            for phase in ("start", "poll", "cancel"):
                operation = OperationSpec(
                    operation_id=f"settings:{spec.action_id}:{phase}",
                    description=spec.description or spec.label,
                    input_schema={
                        "type": "object",
                        "properties": {
                            "session_id": {"type": "string", "minLength": 1},
                            "field_values": {"type": "object"},
                        },
                        "required": ["session_id", "field_values"],
                        "additionalProperties": False,
                    },
                    output_schema=PluginSettingsActionResult.model_json_schema(),
                    triggers=["user"],
                    effect="destructive" if spec.destructive else "external_write",
                    replay="non_idempotent",
                    timeout_seconds=min(spec.timeout_ms / 1000, 3600),
                )

                async def handler(
                    arguments: dict[str, Any],
                    context: ToolExecutionContext,
                    action_phase: str = phase,
                ) -> OperationResult:
                    kwargs = {"session_id": arguments["session_id"]}
                    if action_phase != "cancel":
                        kwargs["field_values"] = arguments["field_values"]
                    remote = getattr(plugin, "invoke_settings_action", None)
                    if callable(remote):
                        result = await remote(
                            action_phase,
                            spec.action_id,
                            **kwargs,
                            identity=context.invocation,
                        )
                    else:
                        callback = getattr(plugin, f"{action_phase}_settings_action")
                        result = await run_plugin_callback_operation(
                            lambda: callback(spec.action_id, **kwargs)
                        )
                        if inspect.isawaitable(result):
                            result = await result
                    value = PluginSettingsActionResult.model_validate(result)
                    return OperationResult(
                        status="succeeded", value=value.model_dump(mode="json")
                    )

                disposers.append(
                    self._operations.register(
                        plugin_id=connection.plugin_id,
                        connection_id=connection.connection_id,
                        spec=operation,
                        handler=handler,
                        allow_disabled=not spec.requires_enabled,
                    )
                )
        except BaseException:
            for dispose in reversed(disposers):
                dispose()
            raise
        self._registrations[key] = (plugin, disposers)

    def _register_resource(
        self,
        connection: PluginConnection,
        plugin: Plugin,
        spec: PluginSettingsResourceSpec,
    ) -> None:
        key = (connection.connection_id, f"resource:{spec.resource_name}")
        previous = self._registrations.get(key)
        if previous is not None and previous[0] is plugin:
            return
        if previous is not None:
            for dispose in reversed(previous[1]):
                dispose()
        operation = OperationSpec(
            operation_id=f"settings-resource:{spec.resource_name}",
            description=spec.description or spec.resource_name,
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={
                "type": ["object", "array", "string", "number", "boolean", "null"]
            },
            effect="read_only",
            replay="read_only",
            triggers=["user"],
        )

        async def handler(
            arguments: dict[str, Any], context: ToolExecutionContext
        ) -> OperationResult:
            reader = getattr(plugin, "read_settings_resource_async", None)
            data = (
                await reader(spec.resource_name, identity=context.invocation)
                if callable(reader)
                else await run_plugin_callback_operation(
                    lambda: plugin.read_settings_resource(spec.resource_name)
                )
            )
            return OperationResult(status="succeeded", value=data)

        dispose = self._operations.register(
            plugin_id=connection.plugin_id,
            connection_id=connection.connection_id,
            spec=operation,
            handler=handler,
            allow_disabled=not getattr(spec, "requires_enabled", True),
        )
        self._registrations[key] = (plugin, [dispose])
