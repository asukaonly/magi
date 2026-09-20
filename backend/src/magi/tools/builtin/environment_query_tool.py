"""Expose bounded client and host observations with explicit ownership."""

from __future__ import annotations

import platform
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from ..schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class _EnvironmentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    section: Literal["client", "service", "location", "all"] = "client"


class EnvironmentQueryTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="environment_query",
            description=(
                "Read this turn's client OS/timezone, the service execution environment, or stored host "
                "location observations. Client facts are advisory snapshots, not device access grants. "
                "The service may run on another machine: its location, OS and workspace do not describe "
                "the user. Respect unknown/stale states; ask for the user's city when it is not established. "
                "Does not capture screens, scan devices, perform live positioning, or write memory. "
                "Use current_time for exact time and get-capabilities for registered tools."
            ),
            category="system",
            effect_replay_policy="read_only",
            timeout=10,
            parameters=[
                ToolParameter(
                    name="section",
                    type=ParameterType.STRING,
                    required=False,
                    default="client",
                    enum=["client", "service", "location", "all"],
                    description="Which bounded environment section to read; defaults to this turn's client.",
                )
            ],
            tags=["environment", "device", "location", "timezone"],
        )

    async def execute(
        self, parameters: dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        try:
            request = _EnvironmentQuery.model_validate(parameters)
        except ValidationError:
            return ToolResult(
                success=False,
                error="Invalid environment query parameters",
                error_code="INVALID_PARAMETERS",
            )
        port = context.capabilities.environment if context.capabilities else None
        data: dict[str, Any] = {}
        if request.section in {"client", "all"}:
            data["client"] = (
                await port.read_client(
                    user_id=context.env_vars.get("user_id", ""),
                    session_id=context.env_vars.get("session_id", ""),
                    turn_id=context.env_vars.get("turn_id", ""),
                )
                if port
                else {"status": "unavailable", "subject": "interaction_client"}
            )
        if request.section in {"service", "all"}:
            data["service"] = {
                "status": "available",
                "subject": "service_host",
                "source": "runtime",
                "os": platform.system(),
                "os_version": platform.release(),
                "workspace": context.workspace,
                "client_device_access": "not_established",
            }
        if request.section in {"location", "all"}:
            data["location"] = (
                await port.read_location()
                if port
                else {
                    "status": "unavailable",
                    "subject": "service_host",
                    "user_location": "unknown",
                }
            )
        return ToolResult(success=True, data=data)
