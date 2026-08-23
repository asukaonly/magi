"""
System Settings Tool - Unified app/tool configuration entrypoint.
"""

from __future__ import annotations

from typing import Any

from ...config import get_config, get_config_file_path, list_app_config_specs, save_config
from ...config.embedding_coordination import (
    clone_config_with_update,
    get_embedding_config_update_lock,
    pause_rebuilds_for_embedding_config_change,
)
from ...core.runtime_bindings import require_embedding_rebuild_manager
from ..schema import (
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
    ParameterType,
)
from .system_settings_actions import SystemSettingsActionsMixin
from .system_settings_paths import SystemSettingsPathMixin
from .system_settings_utils import (
    READ_ONLY_FIELDS,
    SENSITIVE_PATTERNS,
    _get_nested_value,
    _is_read_only_field,
    _is_sensitive_field,
    _serialize_value,
)


def refresh_runtime_llm_config(config: Any) -> None:
    """Refresh runtime adapters after a tool-initiated config write."""

    from ...bootstrap import refresh_runtime_llm_config as refresh

    refresh(config)


def get_embedding_rebuild_manager() -> Any:
    """Return the active embedding rebuild manager."""

    return require_embedding_rebuild_manager()


class SystemSettingsTool(SystemSettingsPathMixin, SystemSettingsActionsMixin, Tool):
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
                    "input": {
                        "action": "set",
                        "path": "tool.web-search.providers.brave.api_key",
                        "value": "your-key",
                    },
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
            effect_replay_policy="reconcilable",
            tags=["system", "config", "settings"],
            metadata={
                "task_intents": ["inspect_config", "apply_change", "inspect_runtime_state"],
                "domains": ["config", "runtime"],
                "operations": ["inspect", "edit"],
                "query_shapes": ["config_path", "setting_value"],
                "followed_by": [],
                "avoid_task_intents": [
                    "explore_codebase",
                    "research_external",
                    "clarify_requirement",
                ],
                "cost": "cheap",
                "tool_hint": "Use to inspect or update Magi runtime and tool configuration; prefer source files when the question is about code behavior rather than live config.",
            },
        )

    async def execute(
        self, parameters: dict[str, Any], context: ToolExecutionContext
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


__all__ = [
    "READ_ONLY_FIELDS",
    "SENSITIVE_PATTERNS",
    "SystemSettingsTool",
    "get_config",
    "get_config_file_path",
    "get_embedding_config_update_lock",
    "get_embedding_rebuild_manager",
    "list_app_config_specs",
    "pause_rebuilds_for_embedding_config_change",
    "refresh_runtime_llm_config",
    "save_config",
    "clone_config_with_update",
    "_get_nested_value",
    "_is_read_only_field",
    "_is_sensitive_field",
    "_serialize_value",
]
