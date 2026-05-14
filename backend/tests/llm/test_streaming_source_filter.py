"""Tests for stream source filtering and think-tag scrubbing."""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from magi.llm.provider_bridge.streaming import ThinkTagScrubber
from magi.llm.streaming_events import (
    LLMStreamEvent,
    emit_stream_event,
    stream_scope,
    stream_source,
)


def _drive(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.asyncio
async def test_emit_drops_text_delta_when_source_is_planner() -> None:
    captured: List[LLMStreamEvent] = []

    async def sink(event: LLMStreamEvent) -> None:
        captured.append(event)

    async with stream_scope(sink, source="chat"):
        async with stream_source("planner"):
            await emit_stream_event(LLMStreamEvent(kind="text_delta", text="leak"))
            await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text="leak"))
            await emit_stream_event(
                LLMStreamEvent(
                    kind="tool_call_start",
                    tool_call_id="t1",
                    tool_name="search",
                )
            )

    kinds = [event.kind for event in captured]
    assert "text_delta" not in kinds
    assert "reasoning_delta" not in kinds
    assert "tool_call_start" in kinds


@pytest.mark.asyncio
async def test_emit_keeps_aggregation_text_sources_visible() -> None:
    captured: List[LLMStreamEvent] = []

    async def sink(event: LLMStreamEvent) -> None:
        captured.append(event)

    async with stream_scope(sink, source="chat"):
        async with stream_source("aggregator"):
            await emit_stream_event(LLMStreamEvent(kind="text_delta", text="final"))
            await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text="thinking"))
        async with stream_source("failure_status"):
            await emit_stream_event(LLMStreamEvent(kind="text_delta", text="failed"))

    assert [(event.kind, event.source, event.text) for event in captured] == [
        ("text_delta", "aggregator", "final"),
        ("reasoning_delta", "aggregator", "thinking"),
        ("text_delta", "failure_status", "failed"),
    ]


@pytest.mark.asyncio
async def test_emit_keeps_status_update_for_non_chat_source() -> None:
    captured: List[LLMStreamEvent] = []

    async def sink(event: LLMStreamEvent) -> None:
        captured.append(event)

    async with stream_scope(sink, source="chat"):
        async with stream_source("planner"):
            await emit_stream_event(LLMStreamEvent(kind="status_update", text="Preparing tools"))

    assert [event.kind for event in captured] == ["status_update"]
    assert captured[0].source == "planner"


@pytest.mark.asyncio
async def test_emit_keeps_text_delta_for_chat_source() -> None:
    captured: List[LLMStreamEvent] = []

    async def sink(event: LLMStreamEvent) -> None:
        captured.append(event)

    async with stream_scope(sink, source="chat"):
        await emit_stream_event(LLMStreamEvent(kind="text_delta", text="hi"))
        await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text="..."))

    kinds = [event.kind for event in captured]
    assert kinds == ["text_delta", "reasoning_delta"]
    assert all(event.source == "chat" for event in captured)


def test_think_scrubber_strips_complete_block() -> None:
    scrubber = ThinkTagScrubber()
    visible, reasoning = scrubber.feed("hello <think>secret</think> world")
    tail_visible, tail_reasoning = scrubber.flush()
    assert visible + tail_visible == "hello  world"
    assert reasoning + tail_reasoning == "secret"


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


def test_think_scrubber_unclosed_block_flushes_as_reasoning() -> None:
    scrubber = ThinkTagScrubber()
    visible, reasoning = scrubber.feed("<think>still thinking")
    tail_visible, tail_reasoning = scrubber.flush()
    assert visible + tail_visible == ""
    assert reasoning + tail_reasoning == "still thinking"


def test_think_scrubber_no_tags_passthrough() -> None:
    scrubber = ThinkTagScrubber()
    visible, reasoning = scrubber.feed("plain content")
    tail_visible, tail_reasoning = scrubber.flush()
    assert visible + tail_visible == "plain content"
    assert reasoning + tail_reasoning == ""
