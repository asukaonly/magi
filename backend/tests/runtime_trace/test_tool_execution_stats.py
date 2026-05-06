from __future__ import annotations

import pytest

from magi.runtime_trace import RuntimeTraceStore
from magi.runtime_trace.contracts import TraceToolRecord


@pytest.mark.asyncio
async def test_tool_execution_stats_are_derived_from_trace_tools(tmp_path) -> None:
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    await store.upsert_tool_call(
        TraceToolRecord(
            span_id="span-success",
            trace_id="trace-1",
            turn_id="turn-1",
            tool_name="web-search",
            tool_call_id="call-1",
            arguments_json="{}",
            success=True,
            execution_time_ms=100,
            error_code=None,
            error_message=None,
            result_preview="ok",
            result_json=None,
        )
    )
    await store.upsert_tool_call(
        TraceToolRecord(
            span_id="span-failed",
            trace_id="trace-2",
            turn_id="turn-2",
            tool_name="web-search",
            tool_call_id="call-2",
            arguments_json="{}",
            success=False,
            execution_time_ms=300,
            error_code="PROVIDER_CHALLENGE",
            error_message="challenge required",
            result_preview=None,
            result_json=None,
        )
    )

    stats = await store.get_tool_execution_stats(["web-search"])

    assert stats["web-search"]["total_calls"] == 2
    assert stats["web-search"]["successful_calls"] == 1
    assert stats["web-search"]["failed_calls"] == 1
    assert stats["web-search"]["success_rate"] == 0.5
    assert stats["web-search"]["avg_execution_time_ms"] == 200.0
