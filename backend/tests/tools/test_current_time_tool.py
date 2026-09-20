"""Tests for exact time as an on-demand runtime capability."""

from __future__ import annotations

from datetime import datetime

import pytest

from magi.tools.builtin.current_time_tool import CurrentTimeTool
from magi.tools.schema import ToolExecutionContext
from magi.tools.system_tools import (
    resolve_resident_system_tools,
    resolve_runtime_fact_tools,
)


@pytest.mark.asyncio
async def test_current_time_returns_second_precision_local_time() -> None:
    result = await CurrentTimeTool().execute(
        {},
        ToolExecutionContext(agent_id="agent"),
    )

    assert result.success
    parsed = datetime.fromisoformat(result.data["local_datetime"])
    assert parsed.tzinfo is not None
    assert parsed.microsecond == 0
    assert result.data["local_date"] == parsed.date().isoformat()
    assert result.data["local_time"] == parsed.time().isoformat(timespec="seconds")
    assert result.data["timezone"]
    assert result.data["basis"] == "service_host"


@pytest.mark.asyncio
async def test_explicit_timezone_uses_current_instant():
    result = await CurrentTimeTool().execute(
        {"timezone": "Asia/Shanghai"}, ToolExecutionContext(agent_id="agent"),
    )
    assert result.success
    assert result.data["basis"] == "requested_timezone"
    assert result.data["utc_offset"] == "+0800"
    assert abs(datetime.now().timestamp() * 1000 - result.data["unix_time_ms"]) < 1000


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [{"timezone": "invalid/zone"}, {"timezone": "/etc/passwd"}, {"target": "user"}, {"os": "macos"}])
async def test_invalid_time_parameters_are_rejected(parameters):
    result = await CurrentTimeTool().execute(parameters, ToolExecutionContext(agent_id="agent"))
    assert not result.success
    assert result.error_code == "INVALID_PARAMETERS"


def test_current_time_is_a_resident_system_tool() -> None:
    class _Registry:
        def list_tools(self, category=None):  # type: ignore[no-untyped-def]
            if category == "control":
                return []
            return ["current_time"]

    assert resolve_resident_system_tools(_Registry()) == ["current_time"]
    assert resolve_runtime_fact_tools(_Registry()) == ["current_time"]
