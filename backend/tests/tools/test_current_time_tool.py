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


def test_current_time_is_a_resident_system_tool() -> None:
    class _Registry:
        def list_tools(self, category=None):  # type: ignore[no-untyped-def]
            if category == "control":
                return []
            return ["current_time"]

    assert resolve_resident_system_tools(_Registry()) == ["current_time"]
    assert resolve_runtime_fact_tools(_Registry()) == ["current_time"]
