"""Tests for ContextCompactor."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from magi.agent.execution.context_compactor import (
    CompactionResult,
    ContextCompactor,
    _CHARS_PER_TOKEN_ESTIMATE,
    _KEEP_RECENT_ROUNDS,
    _LLM_COMPACT_MIN_WINDOW,
    _MAX_CONSECUTIVE_FAILURES,
    _OUTPUT_RESERVE,
    _RULE_KEEP_RECENT_MESSAGES,
    _SAFETY_BUFFER_TOKENS,
    _SUMMARY_OUTPUT_RESERVE,
    _compute_compact_threshold,
    _estimate_message_tokens,
    _group_messages_by_round,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(n: int) -> List[Dict[str, Any]]:
    """Build a sequence of user/assistant message pairs."""
    msgs: list[dict[str, Any]] = []
    for i in range(n):
        if i % 2 == 0:
            msgs.append({"role": "user", "content": f"user message {i}"})
        else:
            msgs.append({"role": "assistant", "content": f"assistant reply {i}"})
    return msgs


def _make_round_messages(rounds: int) -> List[Dict[str, Any]]:
    """Build messages grouped as assistant+tool rounds."""
    msgs: list[dict[str, Any]] = []
    msgs.append({"role": "user", "content": "initial request"})
    for r in range(rounds):
        msgs.append({"role": "assistant", "content": f"thinking {r}", "tool_calls": [{"id": f"tc_{r}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"tc_{r}", "content": f"result {r}"})
    msgs.append({"role": "assistant", "content": "final answer"})
    return msgs


# ---------------------------------------------------------------------------
# _group_messages_by_round
# ---------------------------------------------------------------------------


class TestGroupMessagesByRound:
    def test_empty(self) -> None:
        assert _group_messages_by_round([]) == []

    def test_single_user_message(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        groups = _group_messages_by_round(msgs)
        assert len(groups) == 1
        assert groups[0] == msgs

    def test_alternating_user_assistant(self) -> None:
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        groups = _group_messages_by_round(msgs)
        # Group 0: [user q1]
        # Group 1: [assistant a1, user q2]
        # Group 2: [assistant a2]
        assert len(groups) == 3
        assert groups[0][0]["content"] == "q1"
        assert groups[1][0]["content"] == "a1"
        assert groups[2][0]["content"] == "a2"

    def test_tool_calls_stay_with_assistant(self) -> None:
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "call tool"},
            {"role": "tool", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        groups = _group_messages_by_round(msgs)
        assert len(groups) == 3
        assert groups[1] == [
            {"role": "assistant", "content": "call tool"},
            {"role": "tool", "content": "result"},
        ]


# ---------------------------------------------------------------------------
# _estimate_message_tokens
# ---------------------------------------------------------------------------


class TestEstimateMessageTokens:
    def test_basic_estimate(self) -> None:
        msgs = [{"role": "user", "content": "hello world"}]
        est = _estimate_message_tokens(msgs)
        text = json.dumps(msgs, ensure_ascii=False)
        assert est == max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)

    def test_minimum_one(self) -> None:
        assert _estimate_message_tokens([]) >= 1


# ---------------------------------------------------------------------------
# _compute_compact_threshold
# ---------------------------------------------------------------------------


class TestComputeCompactThreshold:
    def test_standard_window(self) -> None:
        window = 128_000
        expected = window - _OUTPUT_RESERVE - _SUMMARY_OUTPUT_RESERVE - _SAFETY_BUFFER_TOKENS
        assert _compute_compact_threshold(window) == expected

    def test_tiny_window_no_negative(self) -> None:
        assert _compute_compact_threshold(100) == 0


# ---------------------------------------------------------------------------
# ContextCompactor unit tests
# ---------------------------------------------------------------------------


class TestContextCompactorProperties:
    def test_default_window(self) -> None:
        c = ContextCompactor()
        assert c.effective_window == 128_000

    def test_custom_window(self) -> None:
        c = ContextCompactor(context_window=200_000)
        assert c.effective_window == 200_000

    def test_update_context_window(self) -> None:
        c = ContextCompactor(context_window=100_000)
        c.update_context_window(200_000)
        assert c.effective_window == 200_000

    def test_update_context_window_ignores_zero(self) -> None:
        c = ContextCompactor(context_window=100_000)
        c.update_context_window(0)
        assert c.effective_window == 100_000


class TestRecordInputTokens:
    def test_record_positive(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(50_000)
        assert c._last_input_tokens == 50_000

    def test_record_zero_ignored(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(0)
        assert c._last_input_tokens is None

    def test_provider_preferred_over_estimate(self) -> None:
        c = ContextCompactor(context_window=128_000)
        msgs = _make_messages(4)
        # Without provider data, we get char estimate
        est1 = c._current_token_estimate(msgs)

        c.record_input_tokens(42_000)
        est2 = c._current_token_estimate(msgs)
        assert est2 == 42_000
        assert est1 != est2


class TestShouldCompact:
    def test_below_threshold(self) -> None:
        c = ContextCompactor(context_window=128_000)
        small_msgs = [{"role": "user", "content": "hi"}]
        assert c.should_compact(small_msgs) is False

    def test_above_threshold_with_provider_tokens(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(c.compact_threshold + 1)
        assert c.should_compact([{"role": "user", "content": "hi"}]) is True

    def test_circuit_breaker_blocks(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c._consecutive_failures = _MAX_CONSECUTIVE_FAILURES
        c.record_input_tokens(c.compact_threshold + 1)
        assert c.should_compact([]) is False


# ---------------------------------------------------------------------------
# Rule-based compaction
# ---------------------------------------------------------------------------


class TestRuleBasedCompact:
    @pytest.mark.asyncio
    async def test_few_messages_not_compacted(self) -> None:
        c = ContextCompactor(context_window=32_000)  # Below LLM min window
        msgs = _make_messages(4)
        result = await c.compact(msgs)
        assert result.compacted is False
        assert result.messages == msgs

    @pytest.mark.asyncio
    async def test_many_messages_compacted(self) -> None:
        c = ContextCompactor(context_window=32_000)  # Below LLM min window
        msgs = _make_messages(30)
        result = await c.compact(msgs)
        assert result.compacted is True
        assert result.messages[0]["role"] == "system"
        assert "[context truncated]" in result.messages[0]["content"]
        # boundary + _RULE_KEEP_RECENT_MESSAGES
        assert len(result.messages) == _RULE_KEEP_RECENT_MESSAGES + 1

    @pytest.mark.asyncio
    async def test_no_pool_falls_back_to_rule_based(self) -> None:
        c = ContextCompactor(context_window=200_000, scenario_llm_pool=None)
        msgs = _make_messages(30)
        result = await c.compact(msgs)
        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]


# ---------------------------------------------------------------------------
# LLM-based compaction
# ---------------------------------------------------------------------------


class TestLLMCompact:
    @pytest.mark.asyncio
    async def test_llm_compact_success(self) -> None:
        fake_response = SimpleNamespace(content="<analysis>analysis</analysis>\n<summary>summary</summary>")
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=fake_response)

        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(get=lambda scenario: fake_adapter)

        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        msgs = _make_round_messages(rounds=6)

        with patch("magi.agent.execution.context_compactor.LLMProviderBridge", return_value=mock_bridge):
            result = await c.compact(msgs, system_prompt="sys")

        assert result.compacted is True
        assert result.messages[0]["role"] == "system"
        assert "[context compacted]" in result.messages[0]["content"]
        assert "summary" in result.summary_text
        assert c._consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rule_based(self) -> None:
        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(get=lambda scenario: fake_adapter)

        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        msgs = _make_round_messages(rounds=6)

        with patch("magi.agent.execution.context_compactor.LLMProviderBridge", side_effect=RuntimeError("boom")):
            result = await c.compact(msgs, system_prompt="sys")

        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]
        assert c._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_too_few_rounds_not_compacted(self) -> None:
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())

        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        # Only 2 rounds → groups <= _KEEP_RECENT_ROUNDS, skip.
        msgs = _make_round_messages(rounds=2)

        result = await c.compact(msgs, system_prompt="sys")
        assert result.compacted is False
        assert result.messages == msgs


# ---------------------------------------------------------------------------
# Render messages for summary
# ---------------------------------------------------------------------------


class TestRenderMessagesForSummary:
    def test_tool_result_truncation(self) -> None:
        long_content = "x" * 3000
        msgs = [{"role": "tool", "tool_call_id": "t1", "content": long_content}]
        c = ContextCompactor()
        rendered = c._render_messages_for_summary(msgs)
        assert "[truncated]" in rendered
        assert len(rendered) < 3000

    def test_multi_block_assistant(self) -> None:
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "thinking"},
                    {"type": "tool_use", "name": "search", "input": {"q": "test"}},
                ],
            }
        ]
        c = ContextCompactor()
        rendered = c._render_messages_for_summary(msgs)
        assert "thinking" in rendered
        assert "search" in rendered

    def test_user_message(self) -> None:
        msgs = [{"role": "user", "content": "hello"}]
        c = ContextCompactor()
        rendered = c._render_messages_for_summary(msgs)
        assert "user: hello" in rendered


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestEventEmission:
    @pytest.mark.asyncio
    async def test_async_event_callback(self) -> None:
        events: list[dict] = []

        async def on_event(payload: dict) -> None:
            events.append(payload)

        c = ContextCompactor(context_window=32_000, on_event=on_event)
        await c._emit_event("test_stage", {"key": "value"})
        assert len(events) == 1
        assert events[0]["stage"] == "test_stage"
        assert events[0]["key"] == "value"

    @pytest.mark.asyncio
    async def test_sync_event_callback(self) -> None:
        events: list[dict] = []

        def on_event(payload: dict) -> None:
            events.append(payload)

        c = ContextCompactor(context_window=32_000, on_event=on_event)
        await c._emit_event("test_stage", {"data": 1})
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_event_error_swallowed(self) -> None:
        def bad_callback(payload: dict) -> None:
            raise ValueError("oops")

        c = ContextCompactor(context_window=32_000, on_event=bad_callback)
        # Should not raise
        await c._emit_event("stage", {})


# ---------------------------------------------------------------------------
# get_usage tests
# ---------------------------------------------------------------------------

class TestGetUsage:
    def test_returns_none_when_no_tokens_recorded(self) -> None:
        c = ContextCompactor(context_window=128_000)
        assert c.get_usage() is None

    def test_returns_none_for_zero_tokens(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(0)
        assert c.get_usage() is None

    def test_returns_snapshot_after_recording(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(50_000)
        usage = c.get_usage()
        assert usage is not None
        assert usage["used_tokens"] == 50_000
        assert usage["window_size"] == 128_000
        assert usage["threshold"] == _compute_compact_threshold(128_000)

    def test_updates_on_subsequent_calls(self) -> None:
        c = ContextCompactor(context_window=64_000)
        c.record_input_tokens(10_000)
        u1 = c.get_usage()
        c.record_input_tokens(30_000)
        u2 = c.get_usage()
        assert u1 is not None and u2 is not None
        assert u1["used_tokens"] == 10_000
        assert u2["used_tokens"] == 30_000

    def test_uses_default_window_when_none(self) -> None:
        c = ContextCompactor(context_window=None)
        c.record_input_tokens(5_000)
        usage = c.get_usage()
        assert usage is not None
        assert usage["window_size"] == c.effective_window
