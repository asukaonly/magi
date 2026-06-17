"""Path parsing and discovery helpers for system-settings."""

from __future__ import annotations

from typing import Any, Tuple


class SystemSettingsPathMixin:
    """Normalize, parse, and discover app/tool config paths."""

    schema: Any

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

    def _collect_tool_specs(self) -> list[dict[str, Any]]:
        """Collect tool-scoped config specs from registered tools."""
        from ..registry import tool_registry

        specs: list[dict[str, Any]] = []
        for tool_name in tool_registry.list_tools():
            if tool_name == self.schema.name:
                continue

            tool = tool_registry.get_tool(tool_name)
            if not tool:
                continue

            list_specs = getattr(tool, "list_system_config_specs", None)
            config_specs = list_specs() if callable(list_specs) else tool.list_config_specs()
            for item in config_specs:
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


__all__ = ["SystemSettingsPathMixin"]
