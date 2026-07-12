"""Tests for ContextCompactor."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from magi.context.window_budget import build_context_window_budget
from magi.llm.model_context import ModelContextProfile, ResolvedModel
from magi.agent.execution.context_compactor import (
    ContextCompactor,
    _CHARS_PER_TOKEN_ESTIMATE,
    _MAX_CONSECUTIVE_FAILURES,
    _RULE_KEEP_RECENT_MESSAGES,
    _estimate_message_tokens,
    _group_messages_by_round,
)
from magi.agent.execution.function_calling import FunctionCallingOrchestrator


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

    def test_budget_provider_observes_active_model_changes(self) -> None:
        profile = ModelContextProfile(
            provider_id="provider-a",
            model_id="large-model",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
        current = {"profile": profile}
        c = ContextCompactor(
            budget_provider=lambda: build_context_window_budget(current["profile"])
        )

        assert c.effective_window == 1_000_000
        assert c.compact_threshold == 468_000

        current["profile"] = ModelContextProfile(
            provider_id="provider-b",
            model_id="small-model",
            context_window=200_000,
            max_output_tokens=8_000,
        )

        assert c.effective_window == 200_000
        assert c.compact_threshold == 144_000


class TestOrchestratorContextWindow:
    def test_summary_pool_does_not_define_active_model_capacity(self) -> None:
        class _Pool:
            def __init__(self) -> None:
                self.requested: list[str] = []

            def context_window_for(self, scenario: Any) -> int:
                self.requested.append(str(getattr(scenario, "value", scenario)))
                return 65_536

        pool = _Pool()

        orchestrator = FunctionCallingOrchestrator(
            tool_registry=object(),
            scenario_llm_pool=pool,
        )

        assert orchestrator._context_compactor.effective_window == 128_000
        assert pool.requested == []

    def test_uses_the_injected_active_model_instead_of_core(self) -> None:
        resolved = ResolvedModel(
            adapter=SimpleNamespace(provider_name="custom", model_name="worker-model"),
            context=ModelContextProfile(
                provider_id="custom",
                model_id="worker-model",
                context_window=200_000,
                max_output_tokens=8_000,
            ),
        )
        orchestrator = FunctionCallingOrchestrator(
            tool_registry=SimpleNamespace(),
            active_model_provider=lambda: resolved,
        )

        orchestrator.build_step_state(
            turn=SimpleNamespace(text="hello", attachments=[], user_id="u", session_id="s"),
            system_prompt="system",
            selected_tools=[],
        )

        assert orchestrator._context_compactor.effective_window == 200_000
        assert orchestrator._context_compactor.compact_threshold == 144_000


class TestRecordInputTokens:
    def test_record_positive(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(50_000)
        assert c._last_input_tokens == 50_000

    def test_record_zero_ignored(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(0)
        assert c._last_input_tokens is None

    def test_begin_run_clears_previous_request_usage(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(50_000)

        c.begin_run()

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

    def test_message_estimate_used_when_new_tool_result_exceeds_last_provider_count(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(10_000)
        msgs = [
            {"role": "user", "content": "inspect this"},
            {"role": "assistant", "content": "calling tool"},
            {"role": "tool", "tool_call_id": "tool-1", "content": "x" * 400_000},
        ]

        assert c._current_token_estimate(msgs) > c.compact_threshold
        assert c.should_compact(msgs) is True


class TestShouldCompact:
    def test_below_threshold(self) -> None:
        c = ContextCompactor(context_window=128_000)
        small_msgs = [{"role": "user", "content": "hi"}]
        assert c.should_compact(small_msgs) is False

    def test_above_threshold_with_provider_tokens(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(c.compact_threshold + 1)
        assert c.should_compact([{"role": "user", "content": "hi"}]) is True

    def test_counts_system_prompt_and_tool_schemas(self) -> None:
        c = ContextCompactor(context_window=128_000)
        overhead = {
            "system_prompt": "s" * (c.compact_threshold * 4),
            "tools": [{"name": "large_tool", "description": "d" * 8_000}],
        }

        assert c.should_compact(
            [{"role": "user", "content": "hi"}],
            prompt_overhead=overhead,
        ) is True

    def test_circuit_breaker_keeps_detecting_pressure(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c._consecutive_failures = _MAX_CONSECUTIVE_FAILURES
        c.record_input_tokens(c.compact_threshold + 1)
        assert c.should_compact([]) is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_uses_rule_fallback(self) -> None:
        pool = SimpleNamespace(
            get=lambda scenario: (_ for _ in ()).throw(AssertionError("must not call model"))
        )
        c = ContextCompactor(context_window=128_000, scenario_llm_pool=pool)
        c._consecutive_failures = _MAX_CONSECUTIVE_FAILURES
        messages = _make_messages(30)

        result = await c.compact(messages)

        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]


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
        assert result.messages[0]["role"] == "user"
        assert "[context truncated]" in result.messages[0]["content"]
        # Complete rounds may keep slightly fewer than the message-count cap.
        assert 2 <= len(result.messages) <= _RULE_KEEP_RECENT_MESSAGES + 1

    @pytest.mark.asyncio
    async def test_no_pool_falls_back_to_rule_based(self) -> None:
        c = ContextCompactor(context_window=200_000, scenario_llm_pool=None)
        msgs = _make_messages(30)
        result = await c.compact(msgs)
        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_rule_fallback_does_not_orphan_tool_results(self) -> None:
        compactor = ContextCompactor(context_window=32_000)
        messages = [
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "demo"}],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            *[
                {"role": "user", "content": f"follow-up {index}"}
                for index in range(9)
            ],
        ]

        result = await compactor.compact(messages)

        assert result.compacted is True
        assert result.messages[1]["role"] != "tool"

    @pytest.mark.asyncio
    async def test_rule_fallback_truncates_few_oversized_messages(self) -> None:
        compactor = ContextCompactor(context_window=32_000)
        compactor.record_input_tokens(30_000)
        messages = [
            {"role": "user", "content": "begin " + "x" * 120_000 + " end"},
            {"role": "assistant", "content": "answer"},
        ]

        result = await compactor.compact(messages)

        assert result.compacted is True
        assert len(str(result.messages[1]["content"])) < 120_000
        assert "[truncated]" in str(result.messages[1]["content"])
        assert result.messages[-1]["role"] == "assistant"
        assert compactor._last_input_tokens is None


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
        assert result.messages[0]["role"] == "user"
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
    async def test_summary_request_is_chunked_for_summary_model_capacity(self) -> None:
        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(
            resolve=lambda scenario: ResolvedModel(
                adapter=fake_adapter,
                context=ModelContextProfile(
                    provider_id="summary-provider",
                    model_id="small-summary-model",
                    context_window=32_000,
                    max_output_tokens=4_000,
                ),
            )
        )
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(
            side_effect=[
                SimpleNamespace(content="partial summary"),
                SimpleNamespace(content="final cumulative summary"),
            ]
        )
        compactor = ContextCompactor(
            context_window=200_000,
            scenario_llm_pool=fake_pool,
        )

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            summary = await compactor._call_summariser("x" * 100_000)

        assert summary == "final cumulative summary"
        assert mock_bridge.chat.await_count == 2
        second_prompt = mock_bridge.chat.await_args_list[1].kwargs["messages"][0]["content"]
        assert "partial summary" in second_prompt

    @pytest.mark.asyncio
    async def test_empty_summary_never_replaces_history(self) -> None:
        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(get=lambda scenario: fake_adapter)
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="   "))
        compactor = ContextCompactor(
            context_window=200_000,
            scenario_llm_pool=fake_pool,
        )
        messages = _make_round_messages(rounds=6)

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            result = await compactor.compact(messages)

        assert not result.compacted or "[context compacted]" not in result.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_few_large_rounds_are_compacted_under_token_pressure(self) -> None:
        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(get=lambda scenario: fake_adapter)
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="summary"))
        compactor = ContextCompactor(
            context_window=128_000,
            scenario_llm_pool=fake_pool,
        )
        messages = [
            {"role": "user", "content": "x" * 380_000},
            {"role": "assistant", "content": "answer"},
        ]
        assert compactor.should_compact(messages)

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            result = await compactor.compact(messages)

        assert result.compacted is True
        assert result.messages[-1] == messages[-1]

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
        assert usage["threshold"] == c.compact_threshold

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
