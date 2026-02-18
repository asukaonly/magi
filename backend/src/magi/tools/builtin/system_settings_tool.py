"""
System Settings Tool - Query and update runtime configuration values.

Security: This tool blocks access to sensitive fields like API keys.
"""
from typing import Dict, Any, List, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ...config import get_config, reload_config, AppConfig


# Sensitive field patterns that should never be exposed
SENSITIVE_PATTERNS = [
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "auth",
    "private",
]

# Fields that are read-only and cannot be updated
READ_ONLY_FIELDS = [
    "config_path",
    "version",
]


def _is_sensitive_field(field_path: str) -> bool:
    """Check if a field path contains sensitive information."""
    field_lower = field_path.lower()
    return any(pattern in field_lower for pattern in SENSITIVE_PATTERNS)


def _is_read_only_field(field_path: str) -> bool:
    """Check if a field is read-only."""
    field_lower = field_path.lower()
    return any(pattern in field_lower for pattern in READ_ONLY_FIELDS)


def _get_nested_value(obj: Any, path: str) -> tuple[bool, Any, str]:
    """
    Get a nested value from an object using dot notation.

    Args:
        obj: The object to traverse
        path: Dot-separated path (e.g., "agent.llm.model")

    Returns:
        Tuple of (success, value, error_message)
    """
    parts = path.split(".")
    current = obj

    for part in parts:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None, f"Field '{part}' not found in path '{path}'"

    return True, current, ""


def _set_nested_value(obj: Any, path: str, value: Any) -> tuple[bool, str]:
    """
    Set a nested value on an object using dot notation.

    Args:
        obj: The object to modify
        path: Dot-separated path (e.g., "agent.llm.model")
        value: The value to set

    Returns:
        Tuple of (success, error_message)
    """
    parts = path.split(".")
    current = obj

    # Navigate to the parent object
    for part in parts[:-1]:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, f"Field '{part}' not found in path '{path}'"

    # Set the final value
    final_field = parts[-1]

    if hasattr(current, final_field):
        try:
            setattr(current, final_field, value)
            return True, ""
        except Exception as e:
            return False, f"Failed to set field '{final_field}': {str(e)}"
    elif isinstance(current, dict):
        current[final_field] = value
        return True, ""
    else:
        return False, f"Cannot set field '{final_field}' on {type(current).__name__}"


def _serialize_value(value: Any, mask_secrets: bool = True) -> Any:
    """
    Serialize a value for output, masking sensitive data.

    Args:
        value: The value to serialize
        mask_secrets: Whether to mask sensitive values

    Returns:
        Serialized value safe for output
    """
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [_serialize_value(item, mask_secrets) for item in value]

    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if mask_secrets and _is_sensitive_field(k):
                result[k] = "***MASKED***"
            else:
                result[k] = _serialize_value(v, mask_secrets)
        return result

    # For Pydantic models and other objects
    if hasattr(value, "model_dump"):
        return _serialize_value(value.model_dump(), mask_secrets)

    if hasattr(value, "dict"):
        return _serialize_value(value.dict(), mask_secrets)

    if hasattr(value, "__dict__"):
        return _serialize_value(value.__dict__, mask_secrets)

    return str(value)


def _get_config_structure(config: AppConfig) -> Dict[str, Any]:
    """
    Get the structure of available config paths.

    Returns a tree of available configuration paths with descriptions.
    """
    return {
        "agent": {
            "description": "Agent configuration",
            "fields": {
                "name": "Agent name",
                "num_task_agents": "Number of task agents",
                "loop_interval": "Main loop interval in seconds",
                "enable_monitoring": "Enable monitoring",
            },
            "children": {
                "llm": {
                    "description": "LLM configuration",
                    "fields": {
                        "provider": "LLM provider (openai, anthropic, glm, local)",
                        "model": "Model name",
                        "temperature": "Sampling temperature",
                        "max_tokens": "Maximum tokens",
                        "timeout": "Request timeout in seconds",
                        # Note: api_key and base_url are sensitive
                    },
                },
                "memory": {
                    "description": "Memory configuration",
                    "fields": {
                        "retention_days": "Data retention period",
                        "enable_l1_raw": "Enable L1 raw event storage",
                        "enable_l2_relations": "Enable L2 event relations",
                        "enable_l3_embeddings": "Enable L3 embeddings",
                        "enable_l4_summaries": "Enable L4 summaries",
                        "enable_l5_capabilities": "Enable L5 capabilities",
                        "async_embeddings": "Async embedding generation",
                        "auto_extract_relations": "Auto extract relations",
                        "summary_interval_minutes": "Summary interval",
                    },
                },
                "personality": {
                    "description": "Personality configuration",
                    "fields": {
                        "name": "Personality name",
                        "enable_evolution": "Enable personality evolution",
                    },
                },
                "message_bus": {
                    "description": "Message bus configuration",
                    "fields": {
                        "backend": "Backend type (memory, sqlite, redis)",
                        "max_queue_size": "Maximum queue size",
                        "num_workers": "Number of workers",
                    },
                },
            },
        },
        "server": {
            "description": "Server configuration",
            "fields": {
                "host": "Server host address",
                "port": "Server port",
                "debug": "Debug mode",
                "cors_origins": "Allowed CORS origins",
            },
        },
        "debug": "Global debug flag",
        "log_level": "Logging level (DEBUG, INFO, WARNING, ERROR)",
    }


class SystemSettingsTool(Tool):
    """
    System Settings Tool

    Allows querying and updating runtime configuration values.
    Sensitive fields like API keys are never exposed.
    """

    def _init_schema(self) -> None:
        """Initialize schema."""
        self.schema = ToolSchema(
            name="system-settings",
            description=(
                "Query or update system configuration settings. "
                "Use 'action=get' to read values, 'action=set' to update values, "
                "and 'action=list' to see available configuration paths. "
                "Note: Sensitive fields like API keys cannot be read or modified."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action to perform: 'get', 'set', or 'list'",
                    required=True,
                    enum=["get", "set", "list"],
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description=(
                        "Configuration path in dot notation (e.g., 'agent.llm.model'). "
                        "Use 'list' action to see available paths."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="value",
                    type=ParameterType.STRING,
                    description="New value to set (only for 'set' action). Will be auto-converted to appropriate type.",
                    required=False,
                ),
            ],
            examples=[
                {
                    "input": {"action": "list"},
                    "output": "Returns available configuration paths",
                },
                {
                    "input": {"action": "get", "path": "agent.llm.model"},
                    "output": "Returns the current LLM model name",
                },
                {
                    "input": {"action": "set", "path": "agent.llm.temperature", "value": "0.5"},
                    "output": "Updates the LLM temperature (runtime only)",
                },
            ],
            timeout=10,
            retry_on_failure=False,
            dangerous=False,
            tags=["system", "config", "settings"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute settings operation."""
        action = parameters.get("action")
        path = parameters.get("path")
        value = parameters.get("value")

        if action == "list":
            return self._handle_list()

        if action == "get":
            return self._handle_get(path)

        if action == "set":
            return self._handle_set(path, value)

        return ToolResult(
            success=False,
            error=f"Unknown action: {action}",
            error_code="INVALID_ACTION",
        )

    def _handle_list(self) -> ToolResult:
        """Handle list action - show available configuration paths."""
        config = get_config()
        structure = _get_config_structure(config)

        # Build a flat list of available paths
        available_paths = self._flatten_structure(structure, "")

        return ToolResult(
            success=True,
            data={
                "structure": structure,
                "available_paths": available_paths,
                "summary": f"Found {len(available_paths)} configuration paths. Sensitive fields are hidden.",
            },
        )

    def _flatten_structure(self, structure: Dict, prefix: str) -> List[str]:
        """Flatten the config structure into a list of paths."""
        paths = []

        for key, value in structure.items():
            current_path = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                if "fields" in value:
                    for field in value["fields"]:
                        paths.append(f"{current_path}.{field}")
                if "children" in value:
                    paths.extend(self._flatten_structure(value["children"], current_path))
            else:
                paths.append(current_path)

        return paths

    def _handle_get(self, path: Optional[str]) -> ToolResult:
        """Handle get action - retrieve a configuration value."""
        if not path:
            return ToolResult(
                success=False,
                error="Path is required for 'get' action",
                error_code="MISSING_PATH",
            )

        # Security check
        if _is_sensitive_field(path):
            return ToolResult(
                success=False,
                error=f"Access denied: '{path}' contains sensitive information",
                error_code="ACCESS_DENIED",
            )

        config = get_config()
        success, value, error = _get_nested_value(config, path)

        if not success:
            return ToolResult(
                success=False,
                error=error,
                error_code="PATH_NOT_FOUND",
            )

        # Serialize with secret masking (extra safety)
        serialized = _serialize_value(value, mask_secrets=True)

        return ToolResult(
            success=True,
            data={
                "path": path,
                "value": serialized,
                "type": type(value).__name__,
            },
        )

    def _handle_set(self, path: Optional[str], value: Optional[str]) -> ToolResult:
        """Handle set action - update a configuration value."""
        if not path:
            return ToolResult(
                success=False,
                error="Path is required for 'set' action",
                error_code="MISSING_PATH",
            )

        if value is None:
            return ToolResult(
                success=False,
                error="Value is required for 'set' action",
                error_code="MISSING_VALUE",
            )

        # Security check
        if _is_sensitive_field(path):
            return ToolResult(
                success=False,
                error=f"Access denied: Cannot modify '{path}' (sensitive field)",
                error_code="ACCESS_DENIED",
            )

        # Read-only check
        if _is_read_only_field(path):
            return ToolResult(
                success=False,
                error=f"Field '{path}' is read-only",
                error_code="READ_ONLY",
            )

        config = get_config()

        # Get current value to determine type
        success, current_value, error = _get_nested_value(config, path)
        if not success:
            return ToolResult(
                success=False,
                error=error,
                error_code="PATH_NOT_FOUND",
            )

        # Convert value to appropriate type
        try:
            converted_value = self._convert_value(value, current_value)
        except ValueError as e:
            return ToolResult(
                success=False,
                error=f"Type conversion failed: {str(e)}",
                error_code="TYPE_ERROR",
            )

        # Set the value
        success, error = _set_nested_value(config, path, converted_value)

        if not success:
            return ToolResult(
                success=False,
                error=error,
                error_code="SET_FAILED",
            )

        return ToolResult(
            success=True,
            data={
                "path": path,
                "old_value": _serialize_value(current_value, mask_secrets=True),
                "new_value": _serialize_value(converted_value, mask_secrets=True),
                "note": "Change is runtime-only and will be lost on restart",
            },
        )

    def _convert_value(self, value: str, current_value: Any) -> Any:
        """
        Convert string value to the appropriate type based on current value.

        Args:
            value: String value to convert
            current_value: Current value to determine type

        Returns:
            Converted value

        Raises:
            ValueError: If conversion fails
        """
        target_type = type(current_value)

        # Handle None (default to string)
        if current_value is None:
            return value

        # Handle bool
        if target_type == bool:
            if value.lower() in ("true", "1", "yes", "on"):
                return True
            elif value.lower() in ("false", "0", "no", "off"):
                return False
            else:
                raise ValueError(f"Cannot convert '{value}' to boolean")

        # Handle int
        if target_type == int:
            return int(value)

        # Handle float
        if target_type == float:
            return float(value)

        # Handle list (expect JSON or comma-separated)
        if target_type == list:
            import json
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                # Try comma-separated
                return [item.strip() for item in value.split(",")]

        # Default: return as string
        return value
