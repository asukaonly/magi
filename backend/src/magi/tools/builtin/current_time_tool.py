"""On-demand access to the host's exact local time."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...utils.calendar_timezone import local_calendar_timezone_id
from ..schema import Tool, ToolExecutionContext, ToolResult, ToolSchema


class CurrentTimeTool(Tool):
    """Return exact time only when a model explicitly needs it."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="current_time",
            description=(
                "Read the host's exact current local date, time, UTC offset, and timezone. "
                "Use this for time-sensitive questions; do not infer exact time from prompt context."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[],
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
        _ = parameters, context
        now = datetime.now().astimezone()
        return ToolResult(
            success=True,
            data={
                "local_datetime": now.isoformat(timespec="seconds"),
                "local_date": now.date().isoformat(),
                "local_time": now.time().isoformat(timespec="seconds"),
                "timezone": local_calendar_timezone_id() or str(now.tzinfo or "unknown"),
                "utc_offset": now.strftime("%z"),
                "unix_time_ms": int(now.timestamp() * 1000),
            },
        )


__all__ = ["CurrentTimeTool"]
