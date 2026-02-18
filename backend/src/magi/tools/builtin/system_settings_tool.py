"""
System Settings Tool - Query and update configuration values.

Actions:
- list: Show available configuration paths
- get: Read a configuration value
- set: Update a runtime configuration value
- save-env: Save an environment variable to .env file (for API keys, etc.)
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ...config import get_config, reload_config, AppConfig, ENV_MAPPINGS


# Sensitive field patterns (can be read but not via get, use save-env instead)
SENSITIVE_PATTERNS = [
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "private",
]

# Fields that are read-only
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
    """Get a nested value from an object using dot notation."""
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
    """Set a nested value on an object using dot notation."""
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

    if hasattr(value, "dict"):
        return _serialize_value(value.dict(), mask_secrets)

    if hasattr(value, "__dict__"):
        return _serialize_value(value.__dict__, mask_secrets)

    return str(value)


def _get_config_structure(config: AppConfig) -> Dict[str, Any]:
    """Get the structure of available config paths."""
    return {
        "agent": {
            "description": "Agent configuration",
            "fields": {
                "name": "Agent name",
                "num_task_agents": "Number of task agents",
                "loop_interval": "Main loop interval",
                "enable_monitoring": "Enable monitoring",
            },
            "children": {
                "llm": {
                    "description": "LLM configuration",
                    "fields": {
                        "provider": "LLM provider",
                        "model": "Model name",
                        "temperature": "Sampling temperature",
                        "max_tokens": "Maximum tokens",
                        "timeout": "Request timeout",
                    },
                },
                "memory": {
                    "description": "Memory configuration",
                    "fields": {
                        "retention_days": "Data retention days",
                        "enable_l1_raw": "Enable L1 storage",
                        "enable_l2_relations": "Enable L2 relations",
                        "enable_l3_embeddings": "Enable L3 embeddings",
                        "enable_l4_summaries": "Enable L4 summaries",
                        "enable_l5_capabilities": "Enable L5 capabilities",
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
            "fields": {},
            "children": {
                "weather": {
                    "description": "Weather tool (QWeather)",
                    "fields": {
                        "enabled": "Enable weather tool",
                        "default_location": "Default location",
                    },
                    "env_vars": {
                        "QWEATHER_API_KEY": "Weather API key",
                    },
                },
                "web_search": {
                    "description": "Web search tool",
                    "fields": {
                        "enabled": "Enable web search",
                        "engine": "Search engine",
                        "max_results": "Max results",
                    },
                    "env_vars": {
                        "SEARCH_API_KEY": "Search API key",
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


def _find_env_file() -> Optional[Path]:
    """Find .env file location."""
    # Check common locations
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).parent.parent.parent.parent.parent / ".env",  # backend/.env
    ]

    for p in candidates:
        if p.exists():
            return p

    # Default to creating in current directory
    return Path.cwd() / ".env"


def _save_env_var(key: str, value: str) -> tuple[bool, str, Path]:
    """
    Save an environment variable to .env file.

    Returns: (success, error_message, env_file_path)
    """
    env_file = _find_env_file()

    try:
        # Read existing content
        existing_lines = []
        if env_file.exists():
            with open(env_file, 'r') as f:
                existing_lines = f.readlines()

        # Check if key already exists
        key_prefix = f"{key}="
        found = False
        new_lines = []

        for line in existing_lines:
            if line.strip().startswith(key_prefix):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)

        # Add new key if not found
        if not found:
            # Ensure there's a newline before adding
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines.append('\n')
            new_lines.append(f"{key}={value}\n")

        # Write back
        with open(env_file, 'w') as f:
            f.writelines(new_lines)

        # Also set in current environment
        os.environ[key] = value

        return True, "", env_file

    except Exception as e:
        return False, str(e), env_file


class SystemSettingsTool(Tool):
    """
    System Settings Tool

    Allows managing configuration:
    - List available paths
    - Get/set runtime values
    - Save environment variables (for API keys)
    """

    def _init_schema(self) -> None:
        """Initialize schema."""
        self.schema = ToolSchema(
            name="system-settings",
            description=(
                "Manage system configuration. "
                "Actions: 'list' (show paths), 'get' (read value), 'set' (update value), "
                "'save-env' (save API key to .env file). "
                "Use 'save-env' for setting API keys like QWEATHER_API_KEY."
            ),
            category="system",
            version="1.1.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action: 'list', 'get', 'set', or 'save-env'",
                    required=True,
                    enum=["list", "get", "set", "save-env"],
                ),
                ToolParameter(
                    name="path",
                    type=ParameterType.STRING,
                    description="Config path (e.g., 'agent.llm.model'). For 'save-env', use env var name here.",
                    required=False,
                ),
                ToolParameter(
                    name="value",
                    type=ParameterType.STRING,
                    description="Value to set (for 'set' and 'save-env' actions)",
                    required=False,
                ),
            ],
            examples=[
                {
                    "input": {"action": "list"},
                    "output": "Shows available configuration paths",
                },
                {
                    "input": {"action": "save-env", "path": "QWEATHER_API_KEY", "value": "your-api-key"},
                    "output": "Saves API key to .env file and reloads config",
                },
                {
                    "input": {"action": "get", "path": "agent.llm.model"},
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

        if action == "save-env":
            return self._handle_save_env(path, value)

        return ToolResult(
            success=False,
            error=f"Unknown action: {action}. Valid: list, get, set, save-env",
            error_code="INVALID_ACTION",
        )

    def _handle_list(self) -> ToolResult:
        """Handle list action."""
        config = get_config()
        structure = _get_config_structure(config)
        available_paths = self._flatten_structure(structure, "")

        # Also list known env vars
        env_vars = {env_var: desc for _, (env_var, _, _) in ENV_MAPPINGS.items()
                    for desc in [env_var]}

        return ToolResult(
            success=True,
            data={
                "structure": structure,
                "available_paths": available_paths,
                "env_vars": list(set(env_vars.keys())),
                "summary": f"Found {len(available_paths)} config paths. Use 'save-env' to set API keys.",
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

        if _is_sensitive_field(path):
            return ToolResult(
                success=False,
                error=f"Access denied: '{path}' is sensitive. Use 'save-env' to set API keys.",
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
        """Handle set action."""
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

        if _is_sensitive_field(path):
            return ToolResult(
                success=False,
                error=f"Cannot set '{path}' directly. Use 'save-env' action with the env var name.",
                error_code="ACCESS_DENIED",
            )

        if _is_read_only_field(path):
            return ToolResult(
                success=False,
                error=f"Field '{path}' is read-only",
                error_code="READ_ONLY",
            )

        config = get_config()
        success, current_value, error = _get_nested_value(config, path)

        if not success:
            return ToolResult(
                success=False,
                error=error,
                error_code="PATH_NOT_FOUND",
            )

        try:
            converted_value = self._convert_value(value, current_value)
        except ValueError as e:
            return ToolResult(
                success=False,
                error=f"Type conversion failed: {str(e)}",
                error_code="TYPE_ERROR",
            )

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
                "note": "Runtime-only change. Use 'save-env' for persistent settings.",
            },
        )

    def _handle_save_env(self, key: Optional[str], value: Optional[str]) -> ToolResult:
        """Handle save-env action - save to .env file."""
        if not key:
            return ToolResult(
                success=False,
                error="Environment variable name is required for 'save-env' action",
                error_code="MISSING_KEY",
            )

        if value is None:
            return ToolResult(
                success=False,
                error="Value is required for 'save-env' action",
                error_code="MISSING_VALUE",
            )

        # Validate key format (uppercase, underscores)
        if not key.replace("_", "").isalnum() or not key.isupper():
            # Allow lowercase but warn
            pass

        # Save to .env file
        success, error, env_file = _save_env_var(key, value)

        if not success:
            return ToolResult(
                success=False,
                error=f"Failed to save to .env: {error}",
                error_code="SAVE_FAILED",
            )

        # Reload config to pick up the new env var
        try:
            reload_config()
        except Exception as e:
            pass  # Config reload might fail, but env var is saved

        return ToolResult(
            success=True,
            data={
                "key": key,
                "env_file": str(env_file),
                "message": f"Saved {key} to {env_file}. Config reloaded.",
            },
        )

    def _convert_value(self, value: str, current_value: Any) -> Any:
        """Convert string value to appropriate type."""
        target_type = type(current_value)

        if current_value is None:
            return value

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
