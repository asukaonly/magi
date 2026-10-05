"""Tests for exact time as an on-demand runtime capability."""

from __future__ import annotations

from datetime import datetime

import pytest

from magi.tools.builtin.current_time_tool import CurrentTimeTool
from magi.tools.schema import ToolExecutionContext


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters,basis",
    [({}, "service_host"), ({"timezone": "Asia/Shanghai"}, "requested_timezone")],
)
async def test_current_time_returns_the_observed_instant_in_the_requested_zone(parameters, basis):
    before = datetime.now().timestamp()
    result = await CurrentTimeTool().execute(parameters, ToolExecutionContext(agent_id="agent"))
    after = datetime.now().timestamp()
    assert result.success
    instant = result.data["unix_time_ms"] / 1000
    assert before - 0.001 <= instant <= after
    parsed = datetime.fromisoformat(result.data["local_datetime"])
    assert parsed.tzinfo is not None and parsed.microsecond == 0
    assert 0 <= instant - parsed.timestamp() < 1
    assert result.data["local_date"] == parsed.date().isoformat()
    assert result.data["local_time"] == parsed.time().isoformat(timespec="seconds")
    assert result.data["timezone"]
    assert result.data["basis"] == basis
    if parameters:
        assert result.data["timezone"] == "Asia/Shanghai"
        assert result.data["utc_offset"] == "+0800"


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [{"timezone": "invalid/zone"}, {"timezone": "/etc/passwd"}, {"target": "user"}, {"os": "macos"}])
async def test_invalid_time_parameters_are_rejected(parameters):
    result = await CurrentTimeTool().execute(parameters, ToolExecutionContext(agent_id="agent"))
    assert not result.success
    assert result.error_code == "INVALID_PARAMETERS"
