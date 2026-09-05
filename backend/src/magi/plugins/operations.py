"""Connection-bound operations executed by the canonical tool invocation service.

This module adapts contribution contracts to the existing tool registry. The
tool invocation service remains the sole owner of durable effect admission,
tracing and replay governance; operations do not maintain a second ledger.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from magi_plugin_sdk.runtime import (
    InvocationIdentity,
    OperationResult,
    OperationSpec,
    PluginConnection,
    ResourceRef,
)
from magi_plugin_sdk.tools import Tool, ToolExecutionContext, ToolResult, ToolSchema

from ..agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from ..events.domain_payloads import TaskContext
from .operation_progress import publish_operation_progress

OperationHandler = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[OperationResult]]


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    """Reject remote references; validating plugin data must never fetch URLs."""

    def check_refs(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(child, str) or not child.startswith("#")
                ):
                    raise ValueError("Operation schemas may only reference local definitions")
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    json.dumps(schema, allow_nan=False)
    check_refs(schema)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_json(validator: Draft202012Validator, value: Any) -> None:
    json.dumps(value, allow_nan=False)
    validator.validate(value)


def _failure(code: str, message: str, *, uncertain: bool = False) -> OperationResult:
    return OperationResult(
        status="uncertain" if uncertain else "failed", error_code=code, message=message
    )


async def _cancelled(context: ToolExecutionContext) -> bool:
    token = context.cancellation
    if token is None:
        return False
    if isinstance(token, asyncio.Event):
        return token.is_set()
    value = getattr(token, "is_cancelled", getattr(token, "cancelled", False))
    value = value() if callable(value) else value
    return bool(await value if inspect.isawaitable(value) else value)


@dataclass(frozen=True)
class _OperationBinding:
    plugin_id: str
    connection_id: str
    spec: OperationSpec
    handler: OperationHandler
    registered_name: str
    input_validator: Draft202012Validator
    output_validator: Draft202012Validator
    source_tool: Tool | None = None
    allow_disabled: bool = False


class PluginOperationRegistry:
    """Register operations once for model, settings, scheduler and ingress callers."""

    def __init__(
        self,
        tool_registry: Any,
        *,
        get_connection: Callable[[str], PluginConnection | None],
        authorize: Callable[..., Any] | None = None,
        publish_progress: (
            Callable[[InvocationIdentity, dict[str, Any]], Awaitable[None]] | None
        ) = None,
        validate_resource: Callable[[InvocationIdentity, ResourceRef], Any] | None = None,
    ) -> None:
        self._tools = tool_registry
        self._get_connection = get_connection
        self._authorize = authorize
        self._publish_progress = publish_progress or publish_operation_progress
        self._validate_resource = validate_resource
        self._entries: dict[tuple[str, str], _OperationBinding] = {}

    def register(
        self,
        *,
        plugin_id: str,
        connection_id: str,
        spec: OperationSpec,
        handler: OperationHandler,
        registered_name: str | None = None,
        source_tool: Tool | None = None,
        allow_disabled: bool = False,
    ) -> Callable[[], None]:
        """Bind a handler and return a disposer tied to this exact registration."""
        spec = OperationSpec.model_validate(spec.model_dump(mode="json"))
        key = (connection_id, spec.operation_id)
        if key in self._entries:
            raise ValueError(
                f"Operation is already registered: {connection_id}:{spec.operation_id}"
            )
        if spec.input_schema.get("type") != "object":
            raise ValueError("Operation input schema must describe an object")
        if allow_disabled and spec.triggers != ["user"]:
            raise ValueError("Setup operations require the host user trigger")
        if (spec.effect == "read_only") != (spec.replay == "read_only"):
            raise ValueError("Read-only effect and replay declarations must agree")
        if spec.replay == "idempotent_with_key" and not getattr(
            spec, "idempotency_key_parameter", None
        ):
            raise ValueError("Idempotent operations must declare their key parameter")
        binding = _OperationBinding(
            plugin_id,
            connection_id,
            spec,
            handler,
            registered_name or f"{connection_id}:{spec.operation_id}",
            _validator(spec.input_schema),
            _validator(spec.output_schema),
            source_tool,
            allow_disabled,
        )
        registry = self

        class BoundOperationTool(_BoundOperationTool):
            def __init__(self) -> None:
                self._operation_registry = registry
                self._operation_binding = binding
                super().__init__()

        dispose_tool = self._tools.register(
            BoundOperationTool, owner_id=connection_id, plugin_id=plugin_id
        )
        key = (connection_id, spec.operation_id)
        self._entries[key] = binding

        def dispose() -> None:
            dispose_tool()
            if self._entries.get(key) is binding:
                del self._entries[key]

        return dispose

    def register_tool(
        self,
        *,
        plugin_id: str,
        connection_id: str,
        tool_class: type[Tool],
        tool_instance: Tool | None = None,
        registered_name: str | None = None,
    ) -> Callable[[], None]:
        """Project the SDK tool authoring surface onto an operation."""
        tool = tool_instance if tool_instance is not None else tool_class()
        tool._tool_registry_ref = self._tools
        tool._plugin_package_id = plugin_id
        tool._plugin_connection_id = connection_id
        schema = tool.get_schema()
        if schema.effect_class == "unknown" or schema.effect_replay_policy == "unknown":
            raise ValueError(f"Plugin tool {schema.name} must declare its effect and replay policy")
        values = dict(
            operation_id=schema.name,
            description=schema.description,
            input_schema=schema.json_input_schema(),
            output_schema=schema.output_schema,
            triggers=["user", "model", "schedule", "ingress", "system"],
            effect=schema.effect_class,
            replay=schema.effect_replay_policy,
            timeout_seconds=schema.timeout,
        )
        if schema.effect_idempotency_key_parameter:
            values["idempotency_key_parameter"] = schema.effect_idempotency_key_parameter
        spec = OperationSpec(**values)

        async def handler(
            parameters: dict[str, Any], context: ToolExecutionContext
        ) -> OperationResult:
            valid, reason = await tool.validate_parameters(parameters)
            if not valid:
                return _failure("INVALID_PARAMETERS", reason or "Invalid tool parameters")
            result = await tool.after_execution(await tool.execute(parameters, context), context)
            status = result.operation_status or ("succeeded" if result.success else "failed")
            if (
                status == "failed"
                and spec.effect != "read_only"
                and result.metadata.get("effect_state") != "none"
            ):
                status = "uncertain"
            return OperationResult(
                status=status,
                value=result.data,
                resources=result.resources,
                error_code=result.error_code,
                message=result.error,
            )

        return self.register(
            plugin_id=plugin_id,
            connection_id=connection_id,
            spec=spec,
            handler=handler,
            registered_name=registered_name,
            source_tool=tool,
        )

    async def invoke(
        self,
        connection_id: str,
        operation_id: str,
        parameters: dict[str, Any],
        *,
        identity: InvocationIdentity,
        context: ToolExecutionContext | None = None,
    ) -> OperationResult:
        """Invoke through the same host authorization, effect and trace boundary."""
        binding = self._entries.get((connection_id, operation_id))
        if binding is None:
            return _failure("OPERATION_NOT_FOUND", "Operation is not registered")
        execution = context or ToolExecutionContext(agent_id=identity.principal_id)
        execution = execution.model_copy(
            update={
                "invocation": identity,
                "connection": None,
                "env_vars": {
                    **(execution.env_vars or {}),
                    "trace_tool_call_id": identity.invocation_id,
                },
            }
        )
        task_context = TaskContext(
            session_id=identity.session_id,
            task_id=identity.task_id,
            user_id=identity.principal_id,
            turn_id=None,
        )
        try:
            result = await ToolInvocationService(self._tools, require_effect_ledger=True).invoke(
                ToolCall(binding.registered_name, parameters),
                InvocationContext(
                    "plugin_operation",
                    task_context,
                    execution,
                    trigger=identity.trigger,
                ),
            )
        except asyncio.CancelledError:
            return OperationResult(
                status=("cancelled" if binding.spec.effect == "read_only" else "uncertain"),
                error_code="CANCELLED",
                message="Operation was cancelled",
            )
        return OperationResult(
            status=getattr(result, "operation_status", None)
            or ("succeeded" if result.success else "failed"),
            value=result.data,
            resources=getattr(result, "resources", []),
            error_code=result.error_code,
            message=result.error,
        )

    async def admit(
        self,
        binding: _OperationBinding,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult | None:
        """Validate authority and inputs before the durable effect intent is written."""
        identity = context.invocation
        connection = self._get_connection(binding.connection_id)
        if (
            identity is None
            or identity.plugin_id != binding.plugin_id
            or identity.connection_id != binding.connection_id
        ):
            return ToolResult.from_operation(
                _failure(
                    "INVOCATION_IDENTITY_INVALID",
                    "Invocation does not own this operation",
                )
            )
        if (
            connection is None
            or connection.plugin_id != binding.plugin_id
            or (not connection.enabled and not binding.allow_disabled)
        ):
            return ToolResult.from_operation(
                _failure("CONNECTION_DISABLED", "Operation connection is unavailable")
            )
        if self._entries.get((binding.connection_id, binding.spec.operation_id)) is not binding:
            return ToolResult.from_operation(
                _failure("OPERATION_REVOKED", "Operation registration was revoked")
            )
        if identity.trigger not in binding.spec.triggers:
            return ToolResult.from_operation(
                _failure("TRIGGER_NOT_ALLOWED", "Operation does not allow this trigger")
            )
        if await _cancelled(context):
            return ToolResult.from_operation(
                OperationResult(status="cancelled", error_code="CANCELLED")
            )
        try:
            _validate_json(binding.input_validator, parameters)
        except (ValidationError, ValueError, TypeError):
            return ToolResult.from_operation(
                _failure(
                    "INVALID_PARAMETERS",
                    "Operation input does not match its JSON schema",
                )
            )
        if self._authorize is None:
            return ToolResult.from_operation(
                _failure(
                    "PERMISSION_DENIED",
                    "Operation capabilities require host authorization",
                )
            )
        if self._authorize is not None:
            authorize = (
                getattr(self._authorize, "authorize_setup", None)
                if not connection.enabled
                else self._authorize
            )
            if not callable(authorize):
                return ToolResult.from_operation(
                    _failure("PERMISSION_DENIED", "Setup requires host catalog authorization")
                )
            decision = authorize(identity, connection, binding.spec, parameters)
            decision = await decision if inspect.isawaitable(decision) else decision
            if decision is not True:
                return ToolResult.from_operation(
                    _failure("PERMISSION_DENIED", "Operation is not authorized")
                )
        context.connection = connection
        return None

    async def execute(
        self,
        binding: _OperationBinding,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute a validated handler and preserve output uncertainty."""
        active = True

        async def progress(payload: dict[str, Any]) -> None:
            if (
                not active
                or await _cancelled(context)
                or self._entries.get((binding.connection_id, binding.spec.operation_id))
                is not binding
            ):
                raise PermissionError("Operation progress publisher is no longer active")
            json.dumps(payload, allow_nan=False)
            if len(json.dumps(payload)) > 65536:
                raise ValueError("Operation progress exceeds the size limit")
            if self._publish_progress is not None:
                await self._publish_progress(context.invocation, payload)

        context = context.model_copy(update={"progress": progress})

        async def invoke_handler() -> OperationResult:
            task = asyncio.create_task(binding.handler(parameters, context))

            async def watch_cancellation() -> None:
                while not await _cancelled(context):
                    await asyncio.sleep(0.02)

            watcher = (
                asyncio.create_task(watch_cancellation())
                if context.cancellation is not None
                else None
            )
            try:
                if watcher is not None:
                    done, _ = await asyncio.wait(
                        {task, watcher}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if watcher in done:
                        raise asyncio.CancelledError
                return await task
            finally:
                tasks = [task] + ([watcher] if watcher is not None else [])
                for pending in tasks:
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        try:
            result = await asyncio.wait_for(invoke_handler(), binding.spec.timeout_seconds)
            result = OperationResult.model_validate(result)
            if result.status == "succeeded":
                _validate_json(binding.output_validator, result.value)
            for resource in result.resources:
                if (
                    resource.connection_id != binding.connection_id
                    or self._validate_resource is None
                ):
                    raise ValueError("Operation returned an unauthorized resource")
                valid = self._validate_resource(context.invocation, resource)
                valid = await valid if inspect.isawaitable(valid) else valid
                if valid is not True:
                    raise ValueError("Operation resource is unavailable")
            if result.status in {"failed", "cancelled"} and binding.spec.effect != "read_only":
                result = result.model_copy(update={"status": "uncertain"})
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            result = _failure(
                "TIMEOUT",
                "Operation timed out",
                uncertain=binding.spec.effect != "read_only",
            )
        except (ValidationError, ValueError, TypeError):
            result = _failure(
                "INVALID_OPERATION_OUTPUT",
                "Operation output does not match its contract",
                uncertain=binding.spec.effect != "read_only",
            )
        except Exception:
            result = _failure(
                "OPERATION_EXECUTION_ERROR",
                "Operation execution failed",
                uncertain=binding.spec.effect != "read_only",
            )
        finally:
            active = False
        return ToolResult.from_operation(result)


class _BoundOperationTool(Tool):
    _operation_registry: PluginOperationRegistry
    _operation_binding: _OperationBinding

    def _init_schema(self) -> None:
        binding = self._operation_binding
        spec = binding.spec
        source = binding.source_tool
        self.schema = (
            source.get_schema().model_copy(deep=True)
            if source
            else ToolSchema(
                name=binding.registered_name,
                description=spec.description,
                category="plugin_operation",
            )
        )
        self.schema.name = binding.registered_name
        self.schema.input_schema = spec.input_schema
        self.schema.output_schema = spec.output_schema
        self.schema.timeout = spec.timeout_seconds + 1
        self.schema.effect_class = spec.effect
        self.schema.effect_replay_policy = spec.replay
        self.schema.effect_idempotency_key_parameter = getattr(
            spec, "idempotency_key_parameter", None
        )
        self.schema.metadata = {
            **self.schema.metadata,
            "invocation_triggers": list(spec.triggers),
        }

    def prepare_invocation(self, ctx: InvocationContext) -> InvocationContext:
        """Attach host caller identity without accepting identities from arguments."""
        binding = self._operation_binding
        identity = ctx.execution_context.invocation
        if identity is None:
            from .operation_authorization import build_host_invocation

            connection = self._operation_registry._get_connection(binding.connection_id)
            if connection is None:
                raise ValueError("Operation connection is unavailable")
            identity = build_host_invocation(
                connection,
                trigger=ctx.trigger,
                task_id=ctx.task_context.task_id,
                session_id=ctx.task_context.session_id,
            )
        execution = ctx.execution_context.model_copy(update={"invocation": identity})
        return replace(ctx, execution_context=execution)

    async def admit_operation(
        self, parameters: dict[str, Any], ctx: InvocationContext
    ) -> ToolResult | None:
        identity = ctx.execution_context.invocation
        if ctx.task_context.user_id and identity.principal_id != ctx.task_context.user_id:
            return ToolResult.from_operation(
                _failure(
                    "INVOCATION_IDENTITY_INVALID",
                    "Invocation principal does not match the caller",
                )
            )
        if identity.trigger != ctx.trigger:
            return ToolResult.from_operation(
                _failure(
                    "INVOCATION_IDENTITY_INVALID",
                    "Invocation trigger does not match the caller",
                )
            )
        return await self._operation_registry.admit(
            self._operation_binding, dict(parameters), ctx.execution_context
        )

    async def validate_parameters(self, parameters: dict[str, Any]) -> tuple[bool, str | None]:
        try:
            _validate_json(self._operation_binding.input_validator, parameters)
            return True, None
        except (ValidationError, ValueError, TypeError):
            return False, "Operation input does not match its JSON schema"

    async def execute(
        self, parameters: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        if context.connection is None:
            return ToolResult.from_operation(
                _failure(
                    "INVOCATION_REQUIRED",
                    "Operation requires the host invocation service",
                )
            )
        return await self._operation_registry.execute(self._operation_binding, parameters, context)

    def list_config_specs(self) -> list[Any]:
        source = self._operation_binding.source_tool
        return source.list_config_specs() if source else []

    async def clear_user_content(self) -> None:
        source = self._operation_binding.source_tool
        if source:
            await source.clear_user_content()


__all__ = ["PluginOperationRegistry", "OperationHandler"]
