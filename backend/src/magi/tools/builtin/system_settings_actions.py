"""Action handlers for the system-settings tool."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from ..schema import ToolErrorCode, ToolExecutionContext, ToolResult
from ...core.logger import get_logger
from .system_settings_utils import (
    _get_nested_value,
    _is_read_only_field,
    _is_sensitive_field,
    _serialize_value,
)

logger = get_logger(__name__, category="TOOLS")


@dataclass(frozen=True)
class _ParsedSettingsPath:
    normalized_path: str
    scope: str
    tool_name: str | None
    target_path: str


def _facade_config_api() -> Any:
    from . import system_settings_tool

    return system_settings_tool


class SystemSettingsActionsMixin:
    """List, read, and update app/tool configuration values."""

    def _handle_list(self) -> ToolResult:
        """Handle list action."""
        config_api = _facade_config_api()
        app_specs = config_api.list_app_config_specs(prefix="app")
        tool_specs = self._collect_tool_specs()
        available_paths = sorted(
            [item.path for item in app_specs] + [item["path"] for item in tool_specs]
        )

        config_path = str(config_api.get_config_file_path())

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
        parsed = self._prepare_get_path(path)
        if isinstance(parsed, ToolResult):
            return parsed

        if _is_sensitive_field(parsed.normalized_path):
            return self._get_sensitive_value(parsed)
        if parsed.scope == "app":
            return self._get_app_value(parsed)
        return await self._get_tool_value(parsed, context)

    def _prepare_get_path(
        self,
        path: Optional[str],
    ) -> _ParsedSettingsPath | ToolResult:
        if not path:
            return ToolResult(
                success=False,
                error="Path is required for 'get' action",
                error_code=ToolErrorCode.MISSING_PATH.value,
            )

        normalized_path = self._normalize_path(path)

        ok, scope, tool_name, parsed_or_error = self._parse_scope(normalized_path)
        if not ok:
            return ToolResult(
                success=False, error=parsed_or_error, error_code=ToolErrorCode.INVALID_PATH.value
            )
        return _ParsedSettingsPath(
            normalized_path=normalized_path,
            scope=scope,
            tool_name=tool_name if scope == "tool" else None,
            target_path=parsed_or_error,
        )

    @staticmethod
    def _get_sensitive_value(parsed: _ParsedSettingsPath) -> ToolResult:
        config = _facade_config_api().get_config()
        config_path = parsed.target_path
        if parsed.scope == "tool":
            tool_config_name = str(parsed.tool_name or "").replace("-", "_")
            config_path = f"tools.{tool_config_name}.{parsed.target_path}"

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
                "path": parsed.normalized_path,
                "value": "***MASKED***" if configured else None,
                "configured": configured,
                "sensitive": True,
                "scope": parsed.scope,
                "tool": parsed.tool_name if parsed.scope == "tool" else None,
            },
        )

    @staticmethod
    def _get_app_value(parsed: _ParsedSettingsPath) -> ToolResult:
        config = _facade_config_api().get_config()
        success, value, error = _get_nested_value(config, parsed.target_path)
        if not success:
            return ToolResult(
                success=False,
                error=error,
                error_code=ToolErrorCode.PATH_NOT_FOUND.value,
            )
        return ToolResult(
            success=True,
            data={
                "path": parsed.normalized_path,
                "value": _serialize_value(value, mask_secrets=True),
                "type": type(value).__name__,
                "scope": "app",
            },
        )

    async def _get_tool_value(
        self,
        parsed: _ParsedSettingsPath,
        context: ToolExecutionContext,
    ) -> ToolResult:
        from ..registry import tool_registry

        tool = tool_registry.get_tool(parsed.tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool '{parsed.tool_name}' not found",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        tool_result = await tool.get_config_value(parsed.target_path, context)
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
                "path": parsed.normalized_path,
                "value": _serialize_value(tool_result.data, mask_secrets=True),
                "scope": "tool",
                "tool": parsed.tool_name,
            },
        )

    async def _handle_set(
        self, path: Optional[str], value: Optional[str], context: ToolExecutionContext
    ) -> ToolResult:
        """Handle set action - saves to config file."""
        parsed = self._prepare_set_path(path, value)
        if isinstance(parsed, ToolResult):
            return parsed

        if parsed.scope == "app":
            return await self._set_app_value(parsed, value)
        return await self._set_tool_value(parsed, value, context)

    def _prepare_set_path(
        self,
        path: Optional[str],
        value: Optional[str],
    ) -> _ParsedSettingsPath | ToolResult:
        missing = self._validate_set_inputs(path, value)
        if missing is not None:
            return missing

        normalized_path = self._normalize_path(path)
        self._log_set_requested(path, normalized_path, value)

        read_only = self._reject_read_only_path(normalized_path)
        if read_only is not None:
            return read_only

        ok, scope, tool_name, parsed_or_error = self._parse_scope(normalized_path)
        if not ok:
            logger.warning(
                "system-settings set rejected (invalid path)",
                path=normalized_path,
                error=parsed_or_error,
            )
            return ToolResult(
                success=False, error=parsed_or_error, error_code=ToolErrorCode.INVALID_PATH.value
            )

        return _ParsedSettingsPath(
            normalized_path=normalized_path,
            scope=scope,
            tool_name=tool_name if scope == "tool" else None,
            target_path=parsed_or_error,
        )

    @staticmethod
    def _validate_set_inputs(
        path: Optional[str],
        value: Optional[str],
    ) -> ToolResult | None:
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
        return None

    @staticmethod
    def _log_set_requested(
        raw_path: Optional[str],
        normalized_path: str,
        value: Optional[str],
    ) -> None:
        logger.info(
            "system-settings set requested",
            raw_path=raw_path,
            normalized_path=normalized_path,
            value_provided=value is not None,
            value_length=len(str(value)) if value is not None else 0,
            sensitive_path=_is_sensitive_field(normalized_path),
        )

    @staticmethod
    def _reject_read_only_path(normalized_path: str) -> ToolResult | None:
        if not _is_read_only_field(normalized_path):
            return None
        logger.warning("system-settings set rejected (read-only)", path=normalized_path)
        return ToolResult(
            success=False,
            error=f"Field '{normalized_path}' is read-only",
            error_code=ToolErrorCode.READ_ONLY.value,
        )

    async def _set_app_value(
        self,
        parsed: _ParsedSettingsPath,
        value: Optional[str],
    ) -> ToolResult:
        config_api = _facade_config_api()
        async with config_api.get_embedding_config_update_lock():
            current_config = config_api.get_config()
            converted_value = self._convert_app_value(
                parsed.target_path,
                value,
                config=current_config,
            )
            if isinstance(converted_value, ToolResult):
                return converted_value

            try:
                proposed_config = config_api.clone_config_with_update(
                    current_config,
                    parsed.target_path,
                    converted_value,
                )
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                logger.error(
                    "system-settings set failed to prepare app config",
                    path=parsed.normalized_path,
                    config_path=parsed.target_path,
                    error=str(exc),
                )
                return ToolResult(
                    success=False,
                    error="Failed to prepare configuration update",
                    error_code=ToolErrorCode.SAVE_FAILED.value,
                )

            async with config_api.pause_rebuilds_for_embedding_config_change(
                current_config=current_config,
                proposed_config=proposed_config,
                manager_factory=config_api.get_embedding_rebuild_manager,
            ):
                if config_api.save_config({parsed.target_path: converted_value}):
                    try:
                        config_api.refresh_runtime_llm_config(config_api.get_config())
                    except Exception as exc:
                        logger.exception(
                            "system-settings runtime refresh failed after app config save",
                            path=parsed.normalized_path,
                            config_path=parsed.target_path,
                            error=str(exc),
                        )
                        return ToolResult(
                            success=False,
                            error="Configuration was saved but the runtime refresh failed",
                            error_code="RUNTIME_REFRESH_FAILED",
                        )

                    logger.info(
                        "system-settings set saved (app scope)",
                        path=parsed.normalized_path,
                        config_path=parsed.target_path,
                        value_type=type(converted_value).__name__,
                    )
                    return ToolResult(
                        success=True,
                        data={
                            "path": parsed.normalized_path,
                            "new_value": _serialize_value(
                                converted_value,
                                mask_secrets=_is_sensitive_field(parsed.normalized_path),
                            ),
                            "config_file": str(config_api.get_config_file_path()),
                            "message": f"Saved to {config_api.get_config_file_path()}",
                            "scope": "app",
                        },
                    )

        logger.error(
            "system-settings set failed (app scope)",
            path=parsed.normalized_path,
            config_path=parsed.target_path,
        )
        return ToolResult(
            success=False,
            error="Failed to save configuration",
            error_code=ToolErrorCode.SAVE_FAILED.value,
        )

    def _convert_app_value(
        self,
        config_path: str,
        value: Optional[str],
        *,
        config: Any | None = None,
    ) -> Any | ToolResult:
        config = config if config is not None else _facade_config_api().get_config()
        success, current_value, _ = _get_nested_value(config, config_path)
        try:
            if success and current_value is not None:
                return self._convert_value(value, current_value)
            return value
        except ValueError as e:
            return ToolResult(
                success=False,
                error=f"Type conversion failed: {str(e)}",
                error_code=ToolErrorCode.TYPE_ERROR.value,
            )

    async def _set_tool_value(
        self,
        parsed: _ParsedSettingsPath,
        value: Optional[str],
        context: ToolExecutionContext,
    ) -> ToolResult:
        from ..registry import tool_registry

        tool = tool_registry.get_tool(parsed.tool_name)
        if not tool:
            logger.warning(
                "system-settings set rejected (tool not found)",
                path=parsed.normalized_path,
                tool=parsed.tool_name,
            )
            return ToolResult(
                success=False,
                error=f"Tool '{parsed.tool_name}' not found",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        update_result = await tool.update_config(parsed.target_path, value, context)
        if not update_result.success:
            logger.error(
                "system-settings set failed (tool scope)",
                path=parsed.normalized_path,
                tool=parsed.tool_name,
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
            path=parsed.normalized_path,
            tool=parsed.tool_name,
            result_keys=(
                list(update_result.data.keys()) if isinstance(update_result.data, dict) else []
            ),
        )

        return ToolResult(
            success=True,
            data={
                "path": parsed.normalized_path,
                "scope": "tool",
                "tool": parsed.tool_name,
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

        if isinstance(current_value, Enum):
            return target_type(value)

        if target_type == list:
            import json

            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [item.strip() for item in value.split(",")]

        return value


__all__ = ["SystemSettingsActionsMixin"]
