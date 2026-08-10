from __future__ import annotations

from typing import Any, Optional, Protocol

from magi_plugin_sdk.permissions import RiskLevel
from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

from .log_security import redact_mcp_log_text


class _ManagerProto(Protocol):
    async def call_remote(
        self, server_id: str, tool_name: str, args: dict, timeout_ms: int
    ) -> Any: ...


_TYPE_MAP = {
    "string": ParameterType.STRING,
    "integer": ParameterType.INTEGER,
    "number": ParameterType.FLOAT,
    "boolean": ParameterType.BOOLEAN,
    "array": ParameterType.ARRAY,
    "object": ParameterType.OBJECT,
}


def _translate_params(input_schema: dict | None) -> list[ToolParameter]:
    if not input_schema or input_schema.get("type") != "object":
        return []
    props = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])
    out: list[ToolParameter] = []
    for name, sub in props.items():
        ptype = _TYPE_MAP.get(sub.get("type", "string"), ParameterType.STRING)
        item_type = None
        if ptype == ParameterType.ARRAY:
            it = (sub.get("items") or {}).get("type", "string")
            item_type = _TYPE_MAP.get(it, ParameterType.STRING)
        out.append(
            ToolParameter(
                name=name,
                type=ptype,
                description=sub.get("description", ""),
                required=name in required,
                array_item_type=item_type,
            )
        )
    return out


def _infer_risk(annotations: dict | None, override) -> tuple[RiskLevel, str, bool]:
    """Translate MCP hints into Magi's host-owned permission vocabulary.

    MCP annotations are descriptive hints, not an authorization boundary. A
    local override is therefore authoritative, while remote annotations remain
    inputs that host-side classifier rules may promote.
    """

    if override is not None and override.risk is not None:
        return RiskLevel(override.risk), "local_override", True
    if override is not None and override.dangerous is not None:
        legacy_risk = RiskLevel.HIGH if override.dangerous else RiskLevel.LOW
        return legacy_risk, "legacy_local_override", True

    if not annotations:
        return RiskLevel.HIGH, "missing_annotations", False

    read_only = annotations.get("readOnlyHint") is True
    destructive = annotations.get("destructiveHint")
    if read_only and destructive is True:
        return RiskLevel.HIGH, "conflicting_annotations", False
    if read_only:
        return RiskLevel.LOW, "read_only_hint", False
    if destructive is True:
        return RiskLevel.DESTRUCTIVE, "destructive_hint", False
    if destructive is False:
        return RiskLevel.MEDIUM, "additive_update_hint", False
    return RiskLevel.HIGH, "ambiguous_annotations", False


def _infer_user_invocable(annotations: dict | None) -> bool:
    """Surface read-only MCP tools in the `/`-picker by default.

    The MCP `tools/list` response may carry annotations (per the 2025
    spec). When the server marks a tool ``readOnlyHint=true`` we treat
    it as safe enough to expose to the user as a one-click `/` command.
    Anything else (destructive, unknown, missing annotations) stays
    hidden and can still be opted in via the user_invocable_tools.toml
    whitelist.
    """
    if not annotations:
        return False
    return (
        annotations.get("readOnlyHint") is True
        and annotations.get("destructiveHint") is not True
    )


def build_adapter_class(
    server_id: str,
    remote: dict,
    manager: Optional[_ManagerProto],
    call_timeout_ms: int,
    override,
) -> type[Tool]:
    qualified_name = f"mcp__{server_id}__{remote['name']}"
    description = remote.get("description") or ""
    annotations = remote.get("annotations") or {}
    parameters = _translate_params(remote.get("inputSchema"))
    risk, risk_source, risk_authoritative = _infer_risk(annotations, override)
    dangerous = risk >= RiskLevel.HIGH
    user_invocable = _infer_user_invocable(annotations)

    metadata: dict[str, Any] = {
        "mcp_server_id": server_id,
        "mcp_tool_name": remote["name"],
        "permission_risk": risk.value,
        "permission_risk_source": risk_source,
        "permission_risk_authoritative": risk_authoritative,
    }
    if user_invocable:
        metadata["user_invocable"] = True

    schema = ToolSchema(
        name=qualified_name,
        description=description,
        category="mcp",
        parameters=parameters,
        dangerous=dangerous,
        metadata=metadata,
    )

    class _Adapter(Tool):
        def _init_schema(self) -> None:
            self.schema = schema

        async def execute(
            self, parameters: dict, context: Any = None
        ) -> ToolResult:
            try:
                result = await manager.call_remote(  # type: ignore[union-attr]
                    server_id,
                    remote["name"],
                    parameters or {},
                    call_timeout_ms,
                )
            except Exception as exc:
                return ToolResult(
                    success=False,
                    error=redact_mcp_log_text(exc),
                    error_code=ToolErrorCode.EXECUTION_ERROR.value,
                )
            if isinstance(result, dict) and result.get("isError"):
                return ToolResult(
                    success=False,
                    error=redact_mcp_log_text(_extract_text(result)),
                    error_code=ToolErrorCode.EXECUTION_ERROR.value,
                )
            output = redact_mcp_log_text(_extract_text(result)) or ""
            return ToolResult(
                success=True,
                data=result,
                metadata={"output": output},
            )

    _Adapter.__name__ = f"MCPAdapter_{server_id}_{remote['name']}"
    return _Adapter


def _extract_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)
    parts = result.get("content") or []
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(p.get("text", ""))
    return "\n".join(out) if out else ""
