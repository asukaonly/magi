"""
System Settings Tool - Query and update configuration values.

Actions:
- list: Show available configuration paths
- get: Read a configuration value (sensitive fields blocked)
- set: Update a configuration value (persisted to ~/.magi/config/agent.yaml)

Security:
- Sensitive fields (api_key, password, etc.) can be SET but cannot be READ
- This allows AI to configure API keys without exposing existing values
"""
from typing import Dict, Any, List, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ...config import get_config, save_config, get_config_file_path, AppConfig, ENV_MAPPINGS


# Sensitive field patterns (can be set but not read)
SENSITIVE_PATTERNS = [
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "private",
]

# Read-only fields
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
    """Get a nested value using dot notation."""
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
    """Set a nested value using dot notation."""
    parts = path.split(".")
    current = obj

    for part in parts[:-1]:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, f"Field '{part}' not found in path '{path}'"

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
    """Serialize a value for output, masking sensitive data."""
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

    if hasattr(value, "model_dump"):
        return _serialize_value(value.model_dump(), mask_secrets)

    if hasattr(value, "__dict__"):
        return _serialize_value(value.__dict__, mask_secrets)

    return str(value)


def _get_config_structure() -> Dict[str, Any]:
    """Get the structure of available config paths."""
    return {
        "llm": {
            "description": "LLM configuration",
            "fields": {
                "provider": "LLM provider (openai, anthropic, glm)",
                "model": "Model name",
                "api_key": "API key (sensitive)",
                "base_url": "Custom API endpoint",
                "temperature": "Sampling temperature",
                "max_tokens": "Maximum tokens",
                "timeout": "Request timeout",
            },
        },
        "agent": {
            "description": "Agent configuration",
            "fields": {
                "name": "Agent name",
                "num_task_agents": "Number of task agents",
                "loop_interval": "Main loop interval",
            },
            "children": {
                "memory": {
                    "description": "Memory configuration",
                    "fields": {
                        "db_path": "Database path",
                        "retention_days": "Retention days",
                        "enable_l1_raw": "Enable L1 storage",
                        "enable_l3_embeddings": "Enable L3 embeddings",
                    },
                },
                "personality": {
                    "description": "Personality configuration",
                    "fields": {
                        "name": "Personality name",
                        "enable_evolution": "Enable evolution",
                    },
                },
            },
        },
        "tools": {
            "description": "Tool configuration",
            "children": {
                "weather": {
                    "description": "Weather tool (QWeather)",
                    "fields": {
                        "enabled": "Enable weather tool",
                        "api_key": "API key (sensitive)",
                        "default_location": "Default location",
                    },
                },
                "web_search": {
                    "description": "Web search tool",
                    "fields": {
                        "enabled": "Enable web search",
                        "api_key": "API key (sensitive)",
                        "engine": "Search engine",
                        "max_results": "Max results",
                    },
                },
            },
        },
        "features": {
            "description": "Feature flags",
            "fields": {
                "enable_three_layer_arch": "Enable three-layer architecture",
                "enable_skills": "Enable skills",
                "enable_websocket": "Enable WebSocket",
            },
        },
        "server": {
            "description": "Server configuration",
            "fields": {
                "host": "Server host",
                "port": "Server port",
                "debug": "Debug mode",
            },
        },
        "debug": "Global debug flag",
        "log_level": "Logging level",
    }


class SystemSettingsTool(Tool):
    """
    System Settings Tool

    Manage configuration stored in ~/.magi/config/agent.yaml
    - Sensitive fields can be SET but not READ
    """

    def _init_schema(self) -> None:
        """Initialize schema."""
        self.schema = ToolSchema(
            name="system-settings",
            description=(
                "Manage system configuration. "
                "Actions: 'list' (show paths), 'get' (read), 'set' (update and save). "
                "Config is persisted to ~/.magi/config/agent.yaml. "
                "Sensitive fields (api_key) can be SET but not READ."
            ),
            category="system",
            version="2.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action: 'list', 'get', or 'set'",
                    required=True,
                    enum=["list", "get", "set"],
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="Config path (e.g., 'tools.weather.api_key', 'llm.model')",
                    required=False,
                ),
                ToolParameter(
                    name="value",
                    type=ParameterType.STRING,
                    description="Value to set (for 'set' action)",
                    required=False,
                ),
            ],
            examples=[
                {
                    "input": {"action": "list"},
                    "output": "Shows available configuration paths",
                },
                {
                    "input": {"action": "set", "path": "tools.weather.api_key", "value": "your-key"},
                    "output": "Sets weather API key and saves to config file",
                },
                {
                    "input": {"action": "get", "path": "llm.model"},
                    "output": "Returns the current LLM model name",
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
            error=f"Unknown action: {action}. Valid: list, get, set",
            error_code="INVALID_ACTION",
        )

    def _handle_list(self) -> ToolResult:
        """Handle list action."""
        structure = _get_config_structure()
        available_paths = self._flatten_structure(structure, "")

        # Get config file path
        config_path = str(get_config_file_path())

        # List known env vars
        env_vars = list(set(env_var for _, (env_var, _, _) in ENV_MAPPINGS.items()))

        return ToolResult(
            success=True,
            data={
                "structure": structure,
                "available_paths": available_paths,
                "env_vars": env_vars,
                "config_file": config_path,
                "summary": f"Config file: {config_path}. {len(available_paths)} paths available.",
            },
        )

    def _flatten_structure(self, structure: Dict, prefix: str) -> List[str]:
        """Flatten config structure into paths."""
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
        """Handle get action."""
        if not path:
            return ToolResult(
                success=False,
                error="Path is required for 'get' action",
                error_code="MISSING_PATH",
            )

        # Sensitive fields cannot be read
        if _is_sensitive_field(path):
            return ToolResult(
                success=False,
                error=f"Access denied: '{path}' is sensitive and cannot be read. You can set it with 'set' action.",
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

        return ToolResult(
            success=True,
            data={
                "path": path,
                "value": _serialize_value(value, mask_secrets=True),
                "type": type(value).__name__,
            },
        )

    def _handle_set(self, path: Optional[str], value: Optional[str]) -> ToolResult:
        """Handle set action - saves to config file."""
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

        # Read-only check
        if _is_read_only_field(path):
            return ToolResult(
                success=False,
                error=f"Field '{path}' is read-only",
                error_code="READ_ONLY",
            )

        # Get current config for type conversion
        config = get_config()
        success, current_value, error = _get_nested_value(config, path)

        # Convert value to appropriate type
        try:
            if success and current_value is not None:
                converted_value = self._convert_value(value, current_value)
            else:
                converted_value = value
        except ValueError as e:
            return ToolResult(
                success=False,
                error=f"Type conversion failed: {str(e)}",
                error_code="TYPE_ERROR",
            )

        # Save to config file
        if save_config({path: converted_value}):
            return ToolResult(
                success=True,
                data={
                    "path": path,
                    "new_value": _serialize_value(converted_value, mask_secrets=_is_sensitive_field(path)),
                    "config_file": str(get_config_file_path()),
                    "message": f"Saved to {get_config_file_path()}",
                },
            )
        else:
            return ToolResult(
                success=False,
                error="Failed to save configuration",
                error_code="SAVE_FAILED",
            )

    def _convert_value(self, value: str, current_value: Any) -> Any:
        """Convert string value to appropriate type."""
        target_type = type(current_value)

        if target_type == bool:
            if value.lower() in ("true", "1", "yes", "on"):
                return True
            elif value.lower() in ("false", "0", "no", "off"):
                return False
            else:
                raise ValueError(f"Cannot convert '{value}' to boolean")

        if target_type == int:
            return int(value)

        if target_type == float:
            return float(value)

        if target_type == list:
            import json
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [item.strip() for item in value.split(",")]

        return value
