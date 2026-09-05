"""Tool authoring contracts for Magi plugins.

This module intentionally contains only lightweight, host-agnostic tool
contracts and helper logic. Runtime registries, planners, built-in tools,
and provider implementations remain backend-owned.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, JsonValue

from .runtime import InvocationIdentity, OperationResult, PluginConnection, ResourceRef


class ParameterType(str, Enum):
    """Tool parameter type enum."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"


class ToolErrorCode(str, Enum):
    """Standardized tool error codes."""

    PERMISSION_DENIED = "PERMISSION_DENIED"
    ACCESS_DENIED = "ACCESS_DENIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    INVALID_CONFIG = "INVALID_CONFIG"
    INVALID_PROVIDER = "INVALID_PROVIDER"
    INVALID_PATH = "INVALID_PATH"
    INVALID_URL = "INVALID_URL"
    INVALID_ACTION = "INVALID_ACTION"
    INVALID_MODE = "INVALID_MODE"
    INVALID_DAYS = "INVALID_DAYS"
    INVALID_NAME = "INVALID_NAME"
    MISSING_PATH = "MISSING_PATH"
    MISSING_VALUE = "MISSING_VALUE"
    MISSING_LOCATION = "MISSING_LOCATION"
    MISSING_QUERY = "MISSING_QUERY"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNSUPPORTED_PATH = "UNSUPPORTED_PATH"
    READ_ONLY = "READ_ONLY"
    TYPE_ERROR = "TYPE_ERROR"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    PROVIDER_CHALLENGE = "PROVIDER_CHALLENGE"
    NO_PROVIDERS_CONFIGURED = "NO_PROVIDERS_CONFIGURED"
    ALL_PROVIDERS_FAILED = "ALL_PROVIDERS_FAILED"
    CANCELLED = "CANCELLED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    NOT_A_FILE = "NOT_A_FILE"
    NOT_A_DIRECTORY = "NOT_A_DIRECTORY"
    IS_DIRECTORY = "IS_DIRECTORY"
    DIRECTORY_NOT_FOUND = "DIRECTORY_NOT_FOUND"
    OFFSET_OUT_OF_RANGE = "OFFSET_OUT_OF_RANGE"
    READ_ERROR = "READ_ERROR"
    WRITE_ERROR = "WRITE_ERROR"
    DECODE_ERROR = "DECODE_ERROR"
    LIST_ERROR = "LIST_ERROR"
    SAVE_FAILED = "SAVE_FAILED"
    DIR_CREATE_ERROR = "DIR_CREATE_ERROR"
    COMMAND_FAILED = "COMMAND_FAILED"
    FETCH_FAILED = "FETCH_FAILED"
    QWEATHER_BASE_URL_REQUIRED = "QWEATHER_BASE_URL_REQUIRED"


class ToolParameter(BaseModel):
    """Tool parameter definition."""

    name: str = Field(..., description="Parameter name")
    type: ParameterType = Field(..., description="Parameter type")
    description: str = Field(..., description="Parameter description")
    required: bool = Field(default=False, description="Whether required")
    default: Any = Field(None, description="Default value")
    enum: Optional[List[Any]] = Field(None, description="Enum values")
    min_value: Optional[float] = Field(None, description="Minimum value (numeric)")
    max_value: Optional[float] = Field(None, description="Maximum value (numeric)")
    array_item_type: Optional[ParameterType] = Field(
        None,
        description="Array item type when parameter type is array",
    )


class ToolSchema(BaseModel):
    """Tool schema."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    category: str = Field(..., description="Tool category")
    version: str = Field(default="1.0.0", description="Tool version")
    author: str = Field(default="Magi Team", description="Author")
    parameters: List[ToolParameter] = Field(
        default_factory=list, description="Parameter list"
    )
    input_schema: dict[str, JsonValue] | None = None
    output_schema: dict[str, JsonValue] = Field(
        default_factory=lambda: {
            "type": ["object", "array", "string", "number", "boolean", "null"],
        }
    )
    examples: List[Dict[str, Any]] = Field(
        default_factory=list, description="Usage examples"
    )
    timeout: int = Field(default=30, description="Timeout in seconds")
    retry_on_failure: bool = Field(
        default=False, description="Whether to retry on failure"
    )
    max_retries: int = Field(default=3, description="Maximum retry count")
    requires_auth: bool = Field(
        default=False, description="Whether authentication required"
    )
    allowed_roles: List[str] = Field(default_factory=list, description="Allowed roles")
    dangerous: bool = Field(default=False, description="Whether dangerous operation")
    effect_class: Literal[
        "read_only",
        "local_write",
        "external_write",
        "destructive",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "The class of state changed by a successful invocation. Unknown is "
            "fail-closed for capability reuse and automatic completion."
        ),
    )
    effect_replay_policy: Literal[
        "read_only",
        "idempotent",
        "idempotent_with_key",
        "non_idempotent",
        "reconcilable",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "Crash-replay safety for external effects. Unknown is fail-closed "
            "when an earlier attempt has an ambiguous outcome."
        ),
    )
    effect_idempotency_key_parameter: Optional[str] = Field(
        default=None,
        description=(
            "Argument carrying the provider idempotency key when "
            "effect_replay_policy is idempotent_with_key."
        ),
    )
    feature_flags: List[str] = Field(
        default_factory=list, description="Required feature flags"
    )
    tags: List[str] = Field(default_factory=list, description="Tags")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Other metadata")

    def json_input_schema(self) -> dict[str, JsonValue]:
        """Return the complete JSON Schema consumed by invocation and model APIs."""
        if self.input_schema is not None:
            return self.input_schema
        properties: dict[str, JsonValue] = {}
        required: list[JsonValue] = []
        types = {"float": "number", "file": "string"}
        for parameter in self.parameters:
            prop: dict[str, JsonValue] = {
                "type": types.get(parameter.type.value, parameter.type.value),
                "description": parameter.description,
            }
            if parameter.type == ParameterType.ARRAY:
                item_type = parameter.array_item_type or ParameterType.STRING
                prop["items"] = {"type": types.get(item_type.value, item_type.value)}
            if parameter.enum is not None:
                prop["enum"] = parameter.enum
            if parameter.min_value is not None:
                prop["minimum"] = parameter.min_value
            if parameter.max_value is not None:
                prop["maximum"] = parameter.max_value
            if parameter.default is not None:
                prop["default"] = parameter.default
            properties[parameter.name] = prop
            if parameter.required:
                required.append(parameter.name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }


class ToolExecutionContext(BaseModel):
    """Tool execution context."""

    agent_id: str
    invocation: InvocationIdentity | None = None
    connection: PluginConnection | None = None
    progress: Any = Field(
        default=None, description="Host-bound async progress publisher"
    )
    task_id: Optional[str] = None
    workspace: str = Field(default="./workspace", description="Working directory")
    env_vars: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    permissions: List[str] = Field(default_factory=list, description="Permission list")
    enabled_features: List[str] = Field(
        default_factory=list, description="Enabled feature flags"
    )
    cancellation: Any = Field(
        default=None, description="Cooperative cancellation token"
    )
    trace_context: Any = Field(default=None, description="Runtime trace context")
    # Any (not Optional[ToolCapabilities]) on purpose: the bundle carries
    # Protocol-typed/adapter objects pydantic cannot build a schema for —
    # typing it as the dataclass raises PydanticSchemaGenerationError even
    # with arbitrary_types_allowed. Mirrors cancellation/trace_context above.
    capabilities: Any = Field(
        default=None,
        description="Host-injected capability ports (magi_plugin_sdk.capabilities.ToolCapabilities)",
    )


class ToolResult(BaseModel):
    """Tool execution result."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    resources: list[ResourceRef] = Field(default_factory=list)
    operation_status: (
        Literal["succeeded", "failed", "cancelled", "uncertain"] | None
    ) = None

    @classmethod
    def from_operation(cls, result: OperationResult) -> "ToolResult":
        """Preserve uncertain and cancelled outcomes across tool transports."""
        return cls(
            success=result.status == "succeeded",
            data=result.value,
            error=result.message,
            error_code=result.error_code,
            resources=result.resources,
            operation_status=result.status,
        )


class ToolConfigSpec(BaseModel):
    """Tool-managed configuration item."""

    path: str = Field(..., description="Relative config path managed by the tool")
    type: str = Field(default="string", description="Config value type")
    description: str = Field(default="", description="Config item description")
    sensitive: bool = Field(default=False, description="Can be set but not read")
    read_only: bool = Field(default=False, description="Cannot be changed")
    required: bool = Field(default=False, description="Whether this config is required")
    default: Optional[Any] = Field(default=None, description="Default value")
    enum: Optional[List[Any]] = Field(
        default=None, description="Enum values for selection"
    )
    placeholder: Optional[str] = Field(
        default=None, description="Input placeholder hint"
    )
    providers: Optional[List[str]] = Field(
        default=None, description="Providers that this spec applies to"
    )


class Tool(ABC):
    """Tool base class."""

    def __init__(self):
        self.schema: Optional[ToolSchema] = None
        self._init_schema()

    @abstractmethod
    def _init_schema(self) -> None:
        """Initialize tool schema."""

    @abstractmethod
    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute the tool."""

    async def validate_parameters(
        self,
        parameters: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """Validate parameters against the declared schema."""
        if not self.schema:
            return True, None

        for param in self.schema.parameters:
            if param.required and param.name not in parameters:
                return False, f"Missing required parameter: {param.name}"

            if param.name in parameters:
                value = parameters[param.name]

                if param.type == ParameterType.STRING:
                    if not isinstance(value, str):
                        return False, f"Parameter {param.name} must be a string"
                elif param.type == ParameterType.INTEGER:
                    if not isinstance(value, int):
                        return False, f"Parameter {param.name} must be an integer"
                elif param.type == ParameterType.FLOAT:
                    if not isinstance(value, (int, float)):
                        return False, f"Parameter {param.name} must be a number"
                elif param.type == ParameterType.BOOLEAN:
                    if not isinstance(value, bool):
                        return False, f"Parameter {param.name} must be a boolean"
                elif param.type == ParameterType.ARRAY:
                    if not isinstance(value, list):
                        return False, f"Parameter {param.name} must be an array"
                elif param.type == ParameterType.OBJECT:
                    if not isinstance(value, dict):
                        return False, f"Parameter {param.name} must be an object"

                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of {param.enum}"

                if param.min_value is not None and isinstance(value, (int, float)):
                    if value < param.min_value:
                        return (
                            False,
                            f"Parameter {param.name} must be >= {param.min_value}",
                        )

                if param.max_value is not None and isinstance(value, (int, float)):
                    if value > param.max_value:
                        return (
                            False,
                            f"Parameter {param.name} must be <= {param.max_value}",
                        )

        return True, None

    async def before_execution(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> tuple[bool, Optional[str]]:
        """Optional pre-execution hook."""
        return True, None

    async def after_execution(
        self,
        result: ToolResult,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Optional post-execution hook."""
        return result

    async def clear_user_content(self) -> None:
        """Discard user-derived runtime content retained by this tool.

        Tools that keep prompts, query text, fetched content, results, or other
        user-derived values in memory must override this hook. Configuration,
        credentials, and provider clients should be preserved.
        """

    def get_schema(self) -> ToolSchema:
        """Get tool schema."""
        return self.schema

    def get_info(self) -> Dict[str, Any]:
        """Get tool info."""
        return {
            "name": self.schema.name if self.schema else "Unknown",
            "description": self.schema.description if self.schema else "",
            "category": self.schema.category if self.schema else "unknown",
            "parameters": (
                [p.model_dump(mode="json") for p in self.schema.parameters]
                if self.schema
                else []
            ),
            "examples": self.schema.examples if self.schema else [],
            "version": self.schema.version if self.schema else "1.0.0",
            "dangerous": self.schema.dangerous if self.schema else False,
            "tags": list(self.schema.tags) if self.schema else [],
            "metadata": dict(self.schema.metadata) if self.schema else {},
            "input_schema": self.schema.json_input_schema() if self.schema else {},
            "output_schema": self.schema.output_schema if self.schema else {},
        }

    def to_claude_format(self) -> Dict[str, Any]:
        """Convert the tool schema to Claude Tool Use API format."""
        if not self.schema:
            return {}

        return {
            "name": self.schema.name,
            "description": self.schema.description,
            "input_schema": self.schema.json_input_schema(),
        }

    def is_ready(self) -> bool:
        """Check if the tool is ready to use."""
        return True

    def list_config_specs(self) -> List[ToolConfigSpec]:
        """Return tool-managed configuration specs."""
        return []

    async def get_config_value(
        self,
        path: str,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Get tool-managed configuration value."""
        return ToolResult(
            success=False,
            error=f"Tool '{self.schema.name if self.schema else 'unknown'}' does not support reading tool-scoped config",
            error_code="UNSUPPORTED",
        )

    async def update_config(
        self,
        path: str,
        value: Any,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Update tool-managed configuration value."""
        return ToolResult(
            success=False,
            error=f"Tool '{self.schema.name if self.schema else 'unknown'}' does not support updating tool-scoped config",
            error_code="UNSUPPORTED",
        )

    @classmethod
    def from_claude_format(cls, tool_def: Dict[str, Any]) -> ToolSchema:
        """Create a tool schema from Claude Tool Use API format."""
        parameters = []

        input_schema = tool_def.get("input_schema", {})
        props = input_schema.get("properties", {})
        required_list = input_schema.get("required", [])

        for param_name, param_def in props.items():
            param_type = ParameterType.STRING
            if "type" in param_def:
                try:
                    param_type = ParameterType(param_def["type"])
                except ValueError:
                    param_type = ParameterType.STRING

            parameters.append(
                ToolParameter(
                    name=param_name,
                    type=param_type,
                    description=param_def.get("description", ""),
                    required=param_name in required_list,
                    default=param_def.get("default"),
                    enum=param_def.get("enum"),
                    min_value=param_def.get("min"),
                    max_value=param_def.get("max"),
                    array_item_type=(
                        ParameterType(param_def["items"]["type"])
                        if param_type == ParameterType.ARRAY
                        and isinstance(param_def.get("items"), dict)
                        and param_def["items"].get("type")
                        in ParameterType._value2member_map_
                        else None
                    ),
                )
            )

        return ToolSchema(
            name=tool_def.get("name", "unknown"),
            description=tool_def.get("description", ""),
            category="external",
            parameters=parameters,
        )


class MultiProviderTool(Tool):
    """Base class for tools that can execute through multiple providers."""

    def __init__(self):
        super().__init__()
        self._providers: Dict[str, Any] = {}
        self._provider_registry: Any = None
        self._provider_kind: str = "web_search"
        self._register_providers()

    def bind_provider_registry(self, registry: Any, *, kind: str) -> Callable[[], None]:
        """Attach the host's live provider selection seam."""
        binding = (registry, kind, object())
        self._provider_binding = binding
        self._provider_registry = registry
        self._provider_kind = kind

        def dispose() -> None:
            if self._provider_binding is binding:
                self._provider_registry = None

        return dispose

    @property
    def provider_revision(self) -> Any:
        return (
            self._provider_registry.revision
            if self._provider_registry is not None
            else None
        )

    @abstractmethod
    def _register_providers(self) -> None:
        """Register available providers."""

    @abstractmethod
    def _get_provider_config(self, provider_name: str) -> Any:
        """Return provider-specific configuration."""

    @abstractmethod
    def _get_default_provider(self) -> str:
        """Return the default provider name."""

    def register_provider(self, provider: Any) -> Callable[[], None]:
        """Register a provider implementation and return its exact-owner disposer."""
        self._providers[provider.name] = provider

        def dispose() -> None:
            if self._providers.get(provider.name) is provider:
                del self._providers[provider.name]

        return dispose

    def get_provider(self, name: str) -> Optional[Any]:
        """Get a provider by name."""
        if self._provider_registry is not None:
            provider = self._provider_registry.get(self._provider_kind, name)
            if provider is not None:
                return provider
        return self._providers.get(name)

    def get_available_providers(self) -> List[str]:
        """Get provider names that are currently ready to use."""
        available = []
        for name in self.get_all_provider_names():
            provider = self.get_provider(name)
            config = self._get_provider_config(name)
            if provider.is_ready(config):
                available.append(name)
        return available

    def get_all_provider_names(self) -> List[str]:
        """Get all registered provider names."""
        names = list(self._providers)
        if self._provider_registry is not None:
            names.extend(self._provider_registry.names(self._provider_kind))
        return list(dict.fromkeys(names))

    def is_ready(self) -> bool:
        """Check if at least one provider is ready."""
        return len(self.get_available_providers()) > 0

    async def execute_with_provider(
        self,
        provider_name: str,
        params: Dict[str, Any],
    ) -> ToolResult:
        """Execute using a specific provider."""
        provider = self.get_provider(provider_name)

        if not provider:
            return ToolResult(
                success=False,
                error=f"Unknown provider: {provider_name}",
                error_code="INVALID_PROVIDER",
            )

        config = self._get_provider_config(provider_name)

        if not provider.is_ready(config):
            return ToolResult(
                success=False,
                error=f"Provider '{provider_name}' is not configured. Please set the required API key.",
                error_code="PROVIDER_NOT_CONFIGURED",
            )

        try:
            result = await provider.execute(params, config)
            return ToolResult(success=True, data=result)
        except ValueError as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="INVALID_CONFIG",
            )
        except Exception as e:
            if getattr(e, "status_code", None) == 429:
                retry_after_seconds = getattr(e, "retry_after_seconds", None)
                data = (
                    {"retry_after_seconds": retry_after_seconds}
                    if retry_after_seconds is not None
                    else None
                )
                return ToolResult(
                    success=False,
                    data=data,
                    error=str(e),
                    error_code="RATE_LIMITED",
                )
            return ToolResult(
                success=False,
                error=str(e),
                error_code="PROVIDER_ERROR",
            )


__all__ = [
    "MultiProviderTool",
    "ParameterType",
    "Tool",
    "ToolConfigSpec",
    "ToolErrorCode",
    "ToolExecutionContext",
    "ToolParameter",
    "ToolResult",
    "ToolSchema",
]
