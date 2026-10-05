"""Tests for stream source filtering and think-tag scrubbing."""

from __future__ import annotations


import pytest

from magi.llm.provider_bridge.streaming import ThinkTagScrubber
from magi.llm.streaming_events import (
    LLMStreamEvent,
    emit_stream_event,
    stream_scope,
    stream_source,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,visible",
    [("chat", True), ("planner", False), ("aggregator", True), ("failure_status", True)],
)
async def test_stream_visibility_filters_text_but_preserves_control_events(source, visible):
    captured = []

    async def sink(event):
        captured.append(event)

    async with stream_scope(sink, source="chat"):
        async with stream_source(source):
            for kind in ["text_delta", "reasoning_delta", "status_update", "tool_call_start"]:
                await emit_stream_event(
                    LLMStreamEvent(kind=kind, text=kind, tool_call_id="tool", tool_name="search")
                )
        await emit_stream_event(LLMStreamEvent(kind="text_delta", text="restored chat"))
    kinds = (
        ["text_delta", "reasoning_delta", "status_update", "tool_call_start"]
        if visible
        else ["status_update", "tool_call_start"]
    )
    assert [(event.kind, event.source, event.text) for event in captured] == [
        (kind, source, kind) for kind in kinds
    ] + [("text_delta", "chat", "restored chat")]


@pytest.mark.parametrize(
    "case_input_text,case_expected_visible,case_expected_reasoning",
    [
        pytest.param(
            "hello <think>secret</think> world",
            "hello  world",
            "secret",
            id="think_scrubber_strips_complete_block",
        ),
        pytest.param(
            "<think>still thinking",
            "",
            "still thinking",
            id="think_scrubber_unclosed_block_flushes_as_reasoning",
        ),
        pytest.param("plain content", "plain content", "", id="think_scrubber_no_tags_passthrough"),
    ],
)
def test_think_scrubber_separates_visible_and_reasoning_output(
    case_input_text, case_expected_visible, case_expected_reasoning
) -> None:
    scrubber = ThinkTagScrubber()
    visible, reasoning = scrubber.feed(case_input_text)
    tail_visible, tail_reasoning = scrubber.flush()
    assert visible + tail_visible == case_expected_visible
    assert reasoning + tail_reasoning == case_expected_reasoning


def test_think_scrubber_handles_chunk_split_open_tag() -> None:
    scrubber = ThinkTagScrubber()
    visible_a, reasoning_a = scrubber.feed("hi <thi")
    visible_b, reasoning_b = scrubber.feed("nk>secret</think>tail")
    tail_visible, tail_reasoning = scrubber.flush()
    assert visible_a + visible_b + tail_visible == "hi tail"
    assert reasoning_a + reasoning_b + tail_reasoning == "secret"


def test_think_scrubber_handles_chunk_split_close_tag() -> None:
    scrubber = ThinkTagScrubber()
    a_visible, a_reasoning = scrubber.feed("<think>part1")
    b_visible, b_reasoning = scrubber.feed(" part2</thi")
    c_visible, c_reasoning = scrubber.feed("nk>visible")
    tail_visible, tail_reasoning = scrubber.flush()
    assert a_visible + b_visible + c_visible + tail_visible == "visible"
    assert (
        a_reasoning + b_reasoning + c_reasoning + tail_reasoning
        == "part1 part2"
    )
