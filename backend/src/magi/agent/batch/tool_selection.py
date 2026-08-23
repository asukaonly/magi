"""Live-registry validation for batch worker tool selections."""

from __future__ import annotations

from typing import Any, Protocol

from ...tools.platform_tools import native_shell_tool_name

_SHELL_TOOL_NAMES = frozenset({"bash", "powershell"})


class BatchToolSelectionError(ValueError):
    """Raised when a batch requests an unavailable or non-native tool."""


class BatchToolRegistry(Protocol):
    """Registry operations needed to validate the provider-facing tool surface."""

    def resolve_tool_name(self, tool_name: str) -> str: ...

    def get_tool(self, tool_name: str) -> Any | None: ...

    def is_skill(self, skill_name: str) -> bool: ...


def default_batch_tool_names() -> tuple[str, ...]:
    """Return the platform-native default tools for one batch worker run."""
    return (
        "web-search",
        "web-fetch",
        native_shell_tool_name(),
        "file_list",
        "file_info",
        "batch_item_update",
    )


def resolve_batch_tool_names(
    raw_tools: object | None,
    *,
    registry: BatchToolRegistry | None,
) -> list[str]:
    """Validate and canonicalize the tools exposed to a batch worker.

    Validation mirrors the provider-facing schema builder: a name must resolve
    to a registered tool or skill. Shell names have the additional invariant
    that only the host-native dialect may be selected.
    """
    if registry is None:
        raise BatchToolSelectionError("batch tool selection requires the live tool registry")

    if raw_tools is None or raw_tools == []:
        requested: list[object] = list(default_batch_tool_names())
    elif isinstance(raw_tools, list):
        requested = raw_tools
    else:
        raise BatchToolSelectionError("handler_config.tools must be an array of tool names")

    native_shell = native_shell_tool_name()
    resolved: list[str] = []
    for index, raw_name in enumerate(requested):
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise BatchToolSelectionError(
                f"handler_config.tools[{index}] must be a non-empty string"
            )
        requested_name = raw_name.strip()
        canonical_name = registry.resolve_tool_name(requested_name)
        shell_name = canonical_name.casefold()
        if shell_name in _SHELL_TOOL_NAMES and shell_name != native_shell:
            raise BatchToolSelectionError(
                f"batch tool '{requested_name}' is not native on this host; use '{native_shell}'"
            )
        is_registered_tool = registry.get_tool(canonical_name) is not None
        is_registered_skill = registry.is_skill(canonical_name.lstrip("/"))
        if not is_registered_tool and not is_registered_skill:
            raise BatchToolSelectionError(
                f"batch tool '{requested_name}' is not available in the live tool registry"
            )
        if canonical_name not in resolved:
            resolved.append(canonical_name)

    if "batch_item_update" not in resolved:
        if registry.get_tool("batch_item_update") is None:
            raise BatchToolSelectionError(
                "required batch tool 'batch_item_update' is not available in the live tool registry"
            )
        resolved.append("batch_item_update")
    return resolved


__all__ = [
    "BatchToolRegistry",
    "BatchToolSelectionError",
    "default_batch_tool_names",
    "resolve_batch_tool_names",
]
