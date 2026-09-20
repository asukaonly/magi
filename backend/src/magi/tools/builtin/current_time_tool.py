"""Exact time with explicit client, service, or requested timezone provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...core.client_environment import validate_timezone_id
from ...utils.calendar_timezone import local_calendar_timezone_id
from ..schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class _TimeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: Literal["auto", "client", "service"] = "auto"
    timezone: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return validate_timezone_id(value)


class CurrentTimeTool(Tool):
    """Return exact time only when a model explicitly needs it."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="current_time",
            description=(
                "Read exact current date/time and UTC offset. By default use this turn's fresh client "
                "timezone if available, otherwise explicitly report service-host time (not user time). "
                "Set target='client' to require client context, target='service' for the execution host, "
                "or timezone to an explicit IANA zone for a named place. "
                "Check the returned basis before interpreting 'today' or scheduling a user's reminder."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="target",
                    type=ParameterType.STRING,
                    required=False,
                    default="auto",
                    enum=["auto", "client", "service"],
                    description="Whose timezone to use.",
                ),
                ToolParameter(
                    name="timezone",
                    type=ParameterType.STRING,
                    required=False,
                    description="Explicit IANA timezone, such as Asia/Shanghai; overrides target.",
                ),
            ],
            timeout=5,
            retry_on_failure=False,
            dangerous=False,
            effect_replay_policy="read_only",
            tags=["system", "time", "clock", "read_only"],
        )

    async def execute(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        try:
            request = _TimeQuery.model_validate(parameters)
        except ValidationError:
            return ToolResult(
                success=False,
                error="Invalid time query or IANA timezone",
                error_code="INVALID_PARAMETERS",
            )
        now = datetime.now().astimezone()
        timezone = local_calendar_timezone_id() or str(now.tzinfo or "unknown")
        basis = "service_host"
        client_status = "not_requested"
        if request.timezone is not None:
            timezone, basis = request.timezone, "requested_timezone"
            now = now.astimezone(ZoneInfo(timezone))
        elif request.target != "service":
            port = context.capabilities.environment if context.capabilities else None
            client = (
                await port.read_client(
                    user_id=context.env_vars.get("user_id", ""),
                    session_id=context.env_vars.get("session_id", ""),
                    turn_id=context.env_vars.get("turn_id", ""),
                )
                if port
                else {"status": "unavailable"}
            )
            client_status = str(client.get("status") or "unknown")
            client_timezone = client.get("timezone")
            if client_status == "available" and isinstance(client_timezone, str):
                timezone, basis = client_timezone, "interaction_client"
                now = now.astimezone(ZoneInfo(timezone))
            elif request.target == "client":
                return ToolResult(
                    success=False,
                    error="Fresh client timezone is unavailable; ask for a timezone or use service time explicitly",
                    error_code="CLIENT_TIMEZONE_UNAVAILABLE",
                    data={"client_context_status": client_status},
                )
        now = datetime.now(tz=now.tzinfo)
        return ToolResult(
            success=True,
            data={
                "local_datetime": now.isoformat(timespec="seconds"),
                "local_date": now.date().isoformat(),
                "local_time": now.time().isoformat(timespec="seconds"),
                "timezone": timezone,
                "basis": basis,
                "client_context_status": client_status,
                "note": (
                    "Service-host time does not establish the user's local time."
                    if basis == "service_host"
                    else None
                ),
                "utc_offset": now.strftime("%z"),
                "unix_time_ms": int(now.timestamp() * 1000),
            },
        )


__all__ = ["CurrentTimeTool"]
