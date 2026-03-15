"""
System Settings Tool - Unified app/tool configuration entrypoint.
"""
from typing import Dict, Any, List, Optional, Tuple

from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode
from ...config import get_config, save_config, get_config_file_path, list_app_config_specs
from ...core.logger import get_logger


logger = get_logger(__name__, category="TOOLS")


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
                "Unified settings tool for application and tool configuration. "
                "Actions: 'list' (discover paths), 'get' (read value), 'set' (update value). "
                "Use path prefixes: 'app.' for global config and 'tool.<tool_name>.' for tool-scoped config. "
                "Sensitive fields (api_key/secret/token/password) are returned as masked values on 'get' "
                "(with configured status) and can be updated via 'set'."
            ),
            category="system",
            version="3.0.0",
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
                    description="Path to read/update (e.g., 'app.llm.model', 'tool.web-search.providers.brave.api_key')",
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
                    "output": "Shows available app.* and tool.* configuration paths",
                },
                {
                    "input": {"action": "set", "path": "app.llm.model", "value": "gpt-4o-mini"},
                    "output": "Updates global app config and persists to runtime config file",
                },
                {
                    "input": {"action": "set", "path": "tool.web-search.providers.brave.api_key", "value": "your-key"},
                    "output": "Routes update to web-search tool config logic",
                },
                {
                    "input": {"action": "get", "path": "app.llm.model"},
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
            return await self._handle_get(path, context)

        if action == "set":
            return await self._handle_set(path, value, context)

        return ToolResult(
            success=False,
            error=f"Unknown action: {action}. Valid: list, get, set",
            error_code=ToolErrorCode.INVALID_ACTION.value,
        )

    def _normalize_path(self, path: str) -> str:
        """Normalize path for backward-compatible app routes."""
        if path.startswith("app.") or path.startswith("tool."):
            return path

        app_roots = {"llm", "agent", "server", "features", "tools", "debug", "log_level"}
        if path.split(".", 1)[0] in app_roots:
            return f"app.{path}"
        return path

    def _parse_scope(self, raw_path: str) -> Tuple[bool, str, str, str]:
        """Parse path into scope and content."""
        path = self._normalize_path(raw_path)
        if path.startswith("app."):
            return True, "app", "", path[4:]

        if path.startswith("tool."):
            remainder = path[5:]
            if "." not in remainder:
                return False, "", "", "Tool path must be in format 'tool.<tool_name>.<field_path>'"
            tool_name, tool_path = remainder.split(".", 1)
            if not tool_name or not tool_path:
                return False, "", "", "Tool path must include both tool name and field path"
            return True, "tool", tool_name, tool_path

        return (
            False,
            "",
            "",
            "Invalid path prefix. Use 'app.<path>' or 'tool.<tool_name>.<path>'",
        )

    def _collect_tool_specs(self) -> List[Dict[str, Any]]:
        """Collect tool-scoped config specs from registered tools."""
        from ..registry import tool_registry

        specs: List[Dict[str, Any]] = []
        for tool_name in tool_registry.list_tools():
            if tool_name == self.schema.name:
                continue

            tool = tool_registry.get_tool(tool_name)
            if not tool:
                continue

            for item in tool.list_config_specs():
                full_path = f"tool.{tool_name}.{item.path}"
                specs.append(
                    {
                        "path": full_path,
                        "type": item.type,
                        "description": item.description,
                        "sensitive": item.sensitive,
                        "read_only": item.read_only,
                        "scope": "tool",
                        "tool": tool_name,
                    }
                )

        return specs

    def _handle_list(self) -> ToolResult:
        """Handle list action."""
        app_specs = list_app_config_specs(prefix="app")
        tool_specs = self._collect_tool_specs()
        available_paths = sorted([item.path for item in app_specs] + [item["path"] for item in tool_specs])

        # Get config file path
        config_path = str(get_config_file_path())

        return ToolResult(
            success=True,
            data={
                "app_paths": [item.path for item in app_specs],
                "tool_paths": [item["path"] for item in tool_specs],
                "app_specs": [item.model_dump() for item in app_specs],
                "tool_specs": tool_specs,
                "available_paths": available_paths,
                "config_file": config_path,
                "summary": (
                    f"Config file: {config_path}. Found {len(app_specs)} app paths and "
                    f"{len(tool_specs)} tool paths. Use 'set' to update."
                ),
            },
        )

    async def _handle_get(self, path: Optional[str], context: ToolExecutionContext) -> ToolResult:
        """Handle get action."""
        if not path:
            return ToolResult(
                success=False,
                error="Path is required for 'get' action",
                error_code=ToolErrorCode.MISSING_PATH.value,
            )

        normalized_path = self._normalize_path(path)

        ok, scope, tool_name, parsed_or_error = self._parse_scope(normalized_path)
        if not ok:
            return ToolResult(success=False, error=parsed_or_error, error_code=ToolErrorCode.INVALID_PATH.value)

        # Sensitive fields are readable only as masked status
        if _is_sensitive_field(normalized_path):
            config = get_config()

            if scope == "app":
                success, value, error = _get_nested_value(config, parsed_or_error)
                if not success:
                    return ToolResult(
                        success=False,
                        error=error,
                        error_code=ToolErrorCode.PATH_NOT_FOUND.value,
                    )
            else:
                config_path = f"tools.{tool_name.replace('-', '_')}.{parsed_or_error}"
                success, value, error = _get_nested_value(config, config_path)
                if not success:
                    return ToolResult(
                        success=False,
                        error=error,
                        error_code=ToolErrorCode.PATH_NOT_FOUND.value,
                    )

            configured = bool(str(value).strip()) if value is not None else False
            return ToolResult(
                success=True,
                data={
                    "path": normalized_path,
                    "value": "***MASKED***" if configured else None,
                    "configured": configured,
                    "sensitive": True,
                    "scope": scope,
                    "tool": tool_name if scope == "tool" else None,
                },
            )

        if scope == "app":
            config = get_config()
            success, value, error = _get_nested_value(config, parsed_or_error)
            if not success:
                return ToolResult(
                    success=False,
                    error=error,
                    error_code=ToolErrorCode.PATH_NOT_FOUND.value,
                )
            return ToolResult(
                success=True,
                data={
                    "path": normalized_path,
                    "value": _serialize_value(value, mask_secrets=True),
                    "type": type(value).__name__,
                    "scope": "app",
                },
            )

        from ..registry import tool_registry
        tool = tool_registry.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        tool_result = await tool.get_config_value(parsed_or_error, context)
        if not tool_result.success:
            return ToolResult(
                success=False,
                error=tool_result.error,
                error_code=tool_result.error_code or "READ_FAILED",
                data=tool_result.data,
            )

        return ToolResult(
            success=True,
            data={
                "path": normalized_path,
                "value": _serialize_value(tool_result.data, mask_secrets=True),
                "scope": "tool",
                "tool": tool_name,
            },
        )

    async def _handle_set(self, path: Optional[str], value: Optional[str], context: ToolExecutionContext) -> ToolResult:
        """Handle set action - saves to config file."""
        if not path:
            return ToolResult(
                success=False,
                error="Path is required for 'set' action",
                error_code=ToolErrorCode.MISSING_PATH.value,
            )

        if value is None:
            return ToolResult(
                success=False,
                error="Value is required for 'set' action",
                error_code=ToolErrorCode.MISSING_VALUE.value,
            )

        normalized_path = self._normalize_path(path)
        logger.info(
            "system-settings set requested",
            raw_path=path,
            normalized_path=normalized_path,
            value_provided=value is not None,
            value_length=len(str(value)) if value is not None else 0,
            sensitive_path=_is_sensitive_field(normalized_path),
        )

        # Read-only check
        if _is_read_only_field(normalized_path):
            logger.warning("system-settings set rejected (read-only)", path=normalized_path)
            return ToolResult(
                success=False,
                error=f"Field '{normalized_path}' is read-only",
                error_code=ToolErrorCode.READ_ONLY.value,
            )

        ok, scope, tool_name, parsed_or_error = self._parse_scope(normalized_path)
        if not ok:
            logger.warning(
                "system-settings set rejected (invalid path)",
                path=normalized_path,
                error=parsed_or_error,
            )
            return ToolResult(success=False, error=parsed_or_error, error_code=ToolErrorCode.INVALID_PATH.value)

        if scope == "app":
            # Get current config for type conversion
            config = get_config()
            success, current_value, _ = _get_nested_value(config, parsed_or_error)

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
                    error_code=ToolErrorCode.TYPE_ERROR.value,
                )

            if save_config({parsed_or_error: converted_value}):
                logger.info(
                    "system-settings set saved (app scope)",
                    path=normalized_path,
                    config_path=parsed_or_error,
                    value_type=type(converted_value).__name__,
                )
                return ToolResult(
                    success=True,
                    data={
                        "path": normalized_path,
                        "new_value": _serialize_value(converted_value, mask_secrets=_is_sensitive_field(normalized_path)),
                        "config_file": str(get_config_file_path()),
                        "message": f"Saved to {get_config_file_path()}",
                        "scope": "app",
                    },
                )

            logger.error(
                "system-settings set failed (app scope)",
                path=normalized_path,
                config_path=parsed_or_error,
            )
            return ToolResult(
                success=False,
                error="Failed to save configuration",
                error_code=ToolErrorCode.SAVE_FAILED.value,
            )

        from ..registry import tool_registry
        tool = tool_registry.get_tool(tool_name)
        if not tool:
            logger.warning("system-settings set rejected (tool not found)", path=normalized_path, tool=tool_name)
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        update_result = await tool.update_config(parsed_or_error, value, context)
        if not update_result.success:
            logger.error(
                "system-settings set failed (tool scope)",
                path=normalized_path,
                tool=tool_name,
                error_code=update_result.error_code,
                error=update_result.error,
            )
            return ToolResult(
                success=False,
                error=update_result.error,
                error_code=update_result.error_code or "UPDATE_FAILED",
                data=update_result.data,
            )

        logger.info(
            "system-settings set saved (tool scope)",
            path=normalized_path,
            tool=tool_name,
            result_keys=list(update_result.data.keys()) if isinstance(update_result.data, dict) else [],
        )

        return ToolResult(
            success=True,
            data={
                "path": normalized_path,
                "scope": "tool",
                "tool": tool_name,
                "result": _serialize_value(update_result.data, mask_secrets=True),
            },
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
