"""
Tool schema and metadata definitions.

Defines standard tool interface and metadata structure.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING
from pydantic import BaseModel, Field
from enum import Enum

if TYPE_CHECKING:
    from .providers.base import Provider, ProviderConfig


class ParameterType(str, Enum):
    """Parameter type enum."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    FILE = "file"


class ToolErrorCode(str, Enum):
    """
    Standardized tool error codes.

    All error codes follow UPPER_SNAKE_CASE naming convention.
    Categories:
    - Permission/Auth: PERMISSION_*, AUTH_*, ROLE_*
    - Validation: INVALID_*, MISSING_*
    - Execution: EXECUTION_*, TIMEOUT, *_ERROR
    - Provider: PROVIDER_*, *_PROVIDER_*
    - File/Path: *_NOT_FOUND, *_EXISTS, *_ERROR
    """
    # Permission & Authentication
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ACCESS_DENIED = "ACCESS_DENIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"

    # Validation Errors
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

    # Execution Errors
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNSUPPORTED_PATH = "UNSUPPORTED_PATH"
    READ_ONLY = "READ_ONLY"
    TYPE_ERROR = "TYPE_ERROR"

    # Tool Errors
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"

    # Provider Errors
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    PROVIDER_CHALLENGE = "PROVIDER_CHALLENGE"
    NO_PROVIDERS_CONFIGURED = "NO_PROVIDERS_CONFIGURED"
    ALL_PROVIDERS_FAILED = "ALL_PROVIDERS_FAILED"

    # File/Directory Errors
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    NOT_A_FILE = "NOT_A_FILE"
    NOT_A_DIRECTORY = "NOT_A_DIRECTORY"
    IS_DIRECTORY = "IS_DIRECTORY"
    DIRECTORY_NOT_FOUND = "DIRECTORY_NOT_FOUND"
    OFFSET_OUT_OF_RANGE = "OFFSET_OUT_OF_RANGE"

    # I/O Errors
    READ_ERROR = "READ_ERROR"
    WRITE_ERROR = "WRITE_ERROR"
    DECODE_ERROR = "DECODE_ERROR"
    LIST_ERROR = "LIST_ERROR"
    SAVE_FAILED = "SAVE_FAILED"
    DIR_CREATE_ERROR = "DIR_CREATE_ERROR"

    # Command Errors
    COMMAND_FAILED = "COMMAND_FAILED"
    FETCH_FAILED = "FETCH_FAILED"

    # Provider-specific
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
    parameters: List[ToolParameter] = Field(default_factory=list, description="Parameter list")
    examples: List[Dict[str, Any]] = Field(default_factory=list, description="Usage examples")

    # Execution configuration
    timeout: int = Field(default=30, description="Timeout in seconds")
    retry_on_failure: bool = Field(default=False, description="Whether to retry on failure")
    max_retries: int = Field(default=3, description="Maximum retry count")

    # Permission and safety
    requires_auth: bool = Field(default=False, description="Whether authentication required")
    allowed_roles: List[str] = Field(default_factory=list, description="Allowed roles")
    dangerous: bool = Field(default=False, description="Whether dangerous operation")

    # Metadata
    tags: List[str] = Field(default_factory=list, description="Tags")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Other metadata")


class ToolExecutionContext(BaseModel):
    """Tool execution context."""
    agent_id: str
    task_id: Optional[str] = None
    workspace: str = Field(default="./workspace", description="Working directory")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    permissions: List[str] = Field(default_factory=list, description="Permission list")


class ToolResult(BaseModel):
    """Tool execution result."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolConfigSpec(BaseModel):
    """Tool-managed configuration item."""
    path: str = Field(..., description="Relative config path managed by the tool")
    type: str = Field(default="string", description="Config value type")
    description: str = Field(default="", description="Config item description")
    sensitive: bool = Field(default=False, description="Can be set but not read")
    read_only: bool = Field(default=False, description="Cannot be changed")
    required: bool = Field(default=False, description="Whether this config is required")
    default: Optional[Any] = Field(default=None, description="Default value")
    enum: Optional[List[Any]] = Field(default=None, description="Enum values for selection")
    placeholder: Optional[str] = Field(default=None, description="Input placeholder hint")
    providers: Optional[List[str]] = Field(default=None, description="Providers that this spec applies to")


class Tool(ABC):
    """
    Tool base class.

    All tools should inherit from this class and implement the execute method.
    """

    def __init__(self):
        self.schema: Optional[ToolSchema] = None
        self._init_schema()

    @abstractmethod
    def _init_schema(self) -> None:
        """
        Initialize tool schema.

        Subclasses must implement this to define tool metadata.
        """
        pass

    @abstractmethod
    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Execute the tool.

        Args:
            parameters: Tool parameters.
            context: Execution context.

        Returns:
            Execution result.
        """
        pass

    async def validate_parameters(
        self,
        parameters: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """
        Validate parameters.

        Args:
            parameters: Parameters to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if not self.schema:
            return True, None

        # Check required parameters
        for param in self.schema.parameters:
            if param.required and param.name not in parameters:
                return False, f"Missing required parameter: {param.name}"

            # Check type
            if param.name in parameters:
                value = parameters[param.name]

                # Type validation
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

                # Enum validation
                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of {param.enum}"

                # Range validation
                if param.min_value is not None and isinstance(value, (int, float)):
                    if value < param.min_value:
                        return False, f"Parameter {param.name} must be >= {param.min_value}"

                if param.max_value is not None and isinstance(value, (int, float)):
                    if value > param.max_value:
                        return False, f"Parameter {param.name} must be <= {param.max_value}"

        return True, None

    async def before_execution(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> tuple[bool, Optional[str]]:
        """
        Pre-execution hook.

        Subclasses can override for custom pre-execution logic.
        """
        return True, None

    async def after_execution(
        self,
        result: ToolResult,
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Post-execution hook.

        Subclasses can override for custom post-execution logic.
        """
        return result

    def get_schema(self) -> ToolSchema:
        """Get tool schema."""
        return self.schema

    def get_info(self) -> Dict[str, Any]:
        """Get tool info."""
        return {
            "name": self.schema.name if self.schema else "Unknown",
            "description": self.schema.description if self.schema else "",
            "category": self.schema.category if self.schema else "unknown",
            "parameters": [p.model_dump(mode="json") for p in self.schema.parameters] if self.schema else [],
            "examples": self.schema.examples if self.schema else [],
            "version": self.schema.version if self.schema else "1.0.0",
            "dangerous": self.schema.dangerous if self.schema else False,
        }

    def to_claude_format(self) -> Dict[str, Any]:
        """
        Convert to Claude Tool Use API format.

        Claude tools definition format:
        {
            "name": "tool_name",
            "description": "Tool description",
            "input_schema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "..."}
                },
                "required": ["param1"]
            }
        }

        Returns:
            Tool definition in Claude API format.
        """
        if not self.schema:
            return {}

        # Build properties
        properties = {}
        required = []

        for param in self.schema.parameters:
            prop_def = {
                "type": param.type.value,
                "description": param.description,
            }
            if param.type == ParameterType.ARRAY:
                item_type = param.array_item_type or ParameterType.STRING
                prop_def["items"] = {"type": item_type.value}

            # Add default value
            if param.default is not None:
                prop_def["default"] = param.default

            # Add enum values
            if param.enum:
                prop_def["enum"] = param.enum

            # Add range constraints
            if param.min_value is not None:
                prop_def["min"] = param.min_value
            if param.max_value is not None:
                prop_def["max"] = param.max_value

            properties[param.name] = prop_def

            # Collect required parameters
            if param.required:
                required.append(param.name)

        input_schema = {
            "type": "object",
            "properties": properties,
        }

        if required:
            input_schema["required"] = required

        return {
            "name": self.schema.name,
            "description": self.schema.description,
            "input_schema": input_schema,
        }

    def is_ready(self) -> bool:
        """
        Check if the tool is ready to use (has required configuration).

        Override this method in subclasses to check for API keys, etc.
        Tools that return False will not be exposed to the LLM.

        Returns:
            True if the tool is ready to use, False otherwise
        """
        return True  # Default: always ready

    def list_config_specs(self) -> List[ToolConfigSpec]:
        """
        Return tool-managed configuration specs.

        Paths are relative to the tool namespace (for example:
        providers.brave.api_key). Tool settings can then be routed by
        system-settings via `tool.<tool_name>.<relative_path>`.
        """
        return []

    async def get_config_value(
        self,
        path: str,
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Get tool-managed configuration value.

        Subclasses can override when tool config is readable at runtime.
        """
        return ToolResult(
            success=False,
            error=f"Tool '{self.schema.name if self.schema else 'unknown'}' does not support reading tool-scoped config",
            error_code="UNSUPPORTED",
        )

    async def update_config(
        self,
        path: str,
        value: Any,
        context: ToolExecutionContext
    ) -> ToolResult:
        """
        Update tool-managed configuration value.

        Subclasses should override this for tool-specific persistence and
        validation logic.
        """
        return ToolResult(
            success=False,
            error=f"Tool '{self.schema.name if self.schema else 'unknown'}' does not support updating tool-scoped config",
            error_code="UNSUPPORTED",
        )

    @classmethod
    def from_claude_format(cls, tool_def: Dict[str, Any]) -> 'Tool':
        """
        Create tool schema from Claude Tool Use API format.

        Args:
            tool_def: Tool definition in Claude format.

        Returns:
            ToolSchema object.
        """
        from . import registry

        # This is a class method; actual tool creation needs concrete tool class.
        # This returns schema only; concrete tool class implements the tool.
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

            parameters.append(ToolParameter(
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
                    and param_def["items"].get("type") in ParameterType._value2member_map_
                    else None
                ),
            ))

        return ToolSchema(
            name=tool_def.get("name", "unknown"),
            description=tool_def.get("description", ""),
            category="external",  # Tools imported from Claude default to external
            parameters=parameters,
        )


class MultiProviderTool(Tool):
    """
    Base class for tools with multiple service providers.

    This class provides a standardized interface for tools that can use
    multiple backend providers (e.g., different search engines, weather services).

    Subclasses must:
    1. Implement _register_providers() to add available providers
    2. Implement _get_provider_config() to return config for each provider
    """

    def __init__(self):
        super().__init__()
        self._providers: Dict[str, "Provider"] = {}
        self._register_providers()

    @abstractmethod
    def _register_providers(self) -> None:
        """
        Register all available providers.

        Subclasses should call self.register_provider() for each provider.
        """
        pass

    @abstractmethod
    def _get_provider_config(self, provider_name: str) -> "ProviderConfig":
        """
        Get configuration for a specific provider.

        Args:
            provider_name: Name of the provider

        Returns:
            ProviderConfig with API key and other settings
        """
        pass

    @abstractmethod
    def _get_default_provider(self) -> str:
        """
        Get the default provider name.

        Returns:
            Name of the default provider
        """
        pass

    def register_provider(self, provider: "Provider") -> None:
        """
        Register a provider.

        Args:
            provider: Provider instance to register
        """
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> Optional["Provider"]:
        """
        Get a provider by name.

        Args:
            name: Provider identifier

        Returns:
            Provider instance or None if not found
        """
        return self._providers.get(name)

    def get_available_providers(self) -> List[str]:
        """
        Get list of provider names that are ready to use.

        Returns:
            List of provider names that have valid configuration
        """
        available = []
        for name, provider in self._providers.items():
            config = self._get_provider_config(name)
            if provider.is_ready(config):
                available.append(name)
        return available

    def get_all_provider_names(self) -> List[str]:
        """
        Get list of all registered provider names.

        Returns:
            List of all provider names (regardless of configuration)
        """
        return list(self._providers.keys())

    def is_ready(self) -> bool:
        """
        Check if the tool is ready to use.

        Tool is ready if at least one provider is configured.

        Returns:
            True if at least one provider is ready
        """
        return len(self.get_available_providers()) > 0

    async def execute_with_provider(
        self,
        provider_name: str,
        params: Dict[str, Any]
    ) -> ToolResult:
        """
        Execute using a specific provider.

        Args:
            provider_name: Name of the provider to use
            params: Parameters for the provider

        Returns:
            ToolResult with success/failure and data
        """
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
            return ToolResult(
                success=False,
                error=str(e),
                error_code="PROVIDER_ERROR",
            )
