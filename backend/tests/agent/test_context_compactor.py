"""Tests for ContextCompactor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from magi.agent.execution.context_compactor import (
    ContextCompactor,
    CompactionResult,
    _CIRCUIT_RETRY_SECONDS,
    _MAX_CONSECUTIVE_FAILURES,
    _group_messages_by_round,
    _group_messages_by_user_turn,
)
from magi.agent.execution.function_calling import FunctionCallingOrchestrator
from magi.context.window_budget import build_context_window_budget
from magi.llm.model_context import ModelContextProfile, ResolvedModel
from magi.utils.model_context_messages import (
    build_launch_context_message,
    build_runtime_world_state_message,
    build_working_context_message,
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
        msgs.append(
            {"role": "assistant", "content": f"thinking {r}", "tool_calls": [{"id": f"tc_{r}"}]}
        )
        msgs.append({"role": "tool", "tool_call_id": f"tc_{r}", "content": f"result {r}"})
    msgs.append({"role": "assistant", "content": "final answer"})
    return msgs


# ---------------------------------------------------------------------------
# _group_messages_by_round
# ---------------------------------------------------------------------------


class TestGroupMessagesByRound:
    @pytest.mark.parametrize(
        "messages,expected",
        [([], []), ([{"role": "user", "content": "hi"}], [[{"role": "user", "content": "hi"}]])],
    )
    def test_grouping_handles_empty_and_leading_user_input(self, messages, expected):
        assert _group_messages_by_round(messages) == expected


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


class TestGroupMessagesByUserTurn:
    def test_alternating_messages_keep_questions_with_answers(self) -> None:
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]

        groups = _group_messages_by_user_turn(messages)

        assert groups == [messages[:2], messages[2:]]

    def test_tool_sequence_stays_with_its_user_request(self) -> None:
        messages = [
            {"role": "user", "content": "inspect"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "demo"}],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]

        assert _group_messages_by_user_turn(messages) == [messages]


# ---------------------------------------------------------------------------
# _estimate_message_tokens
# ---------------------------------------------------------------------------


def test_summary_renderer_replaces_inline_image_bytes_with_marker() -> None:
    image_data = "A" * 600_000
    rendered = ContextCompactor._render_messages_for_summary(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this."},
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "data": image_data,
                    },
                ],
            }
        ]
    )

    assert "Describe this." in rendered
    assert "[image input mime_type=image/png]" in rendered
    assert image_data not in rendered


# ---------------------------------------------------------------------------
# ContextCompactor unit tests
# ---------------------------------------------------------------------------


class TestContextCompactorProperties:
    @pytest.mark.parametrize(
        "window,expected_window,initial_pressure",
        [(None, 128_000, True), (100_000, 100_000, True), (200_000, 200_000, False)],
    )
    def test_configured_window_updates_change_compaction_decision(
        self, window, expected_window, initial_pressure
    ):
        c = ContextCompactor(context_window=window)
        c.record_input_tokens(100_000)
        assert c.get_usage()["window_size"] == expected_window
        assert c.should_compact([]) is initial_pressure
        c.update_context_window(200_000)
        assert c.should_compact([]) is False
        for invalid in [0, None, -1]:
            c.update_context_window(invalid)
            assert c.get_usage()["window_size"] == 200_000
            assert c.should_compact([]) is False
        c.update_context_window(100_000)
        assert c.should_compact([]) is True


    def test_budget_provider_observes_active_model_changes(self) -> None:
        profile = ModelContextProfile(
            provider_id="provider-a",
            model_id="large-model",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
        current = {"profile": profile}
        c = ContextCompactor(budget_provider=lambda: build_context_window_budget(current["profile"]))

        c.record_input_tokens(200_000)
        assert c.should_compact([]) is False
        assert c.effective_window == 1_000_000
        assert c.compact_threshold == 468_000

        current["profile"] = ModelContextProfile(
            provider_id="provider-b",
            model_id="small-model",
            context_window=200_000,
            max_output_tokens=8_000,
        )

        assert c.should_compact([]) is True
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
    @pytest.mark.parametrize(
        "tokens,expected", [(0, False), (89_855, False), (89_856, True), (89_857, True)]
    )
    def test_provider_usage_crosses_exact_compaction_boundary(self, tokens, expected):
        c = ContextCompactor(context_window=128_000)
        c.record_input_tokens(tokens)
        assert c.should_compact([{"role": "user", "content": "hi"}]) is expected


    @pytest.mark.parametrize("component", ["system", "tools"])
    @pytest.mark.parametrize("size,expected", [(100, False), (80_000, True)])
    def test_prompt_components_independently_trigger_compaction(self, component, size, expected):
        c = ContextCompactor(context_window=32_000)
        overhead = (
            {"system_prompt": "s" * size}
            if component == "system"
            else {"tools": [{"name": "large_tool", "description": "d" * size}]}
        )
        messages = [{"role": "user", "content": "hi"}]
        assert c.should_compact(messages) is False
        assert c.should_compact(messages, prompt_overhead=overhead) is expected

    def test_circuit_breaker_keeps_detecting_pressure(self) -> None:
        c = ContextCompactor(context_window=128_000)
        c._consecutive_failures = _MAX_CONSECUTIVE_FAILURES
        c.record_input_tokens(c.compact_threshold + 1)
        assert c.should_compact([]) is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_uses_rule_fallback(self) -> None:
        from unittest.mock import Mock

        pool = SimpleNamespace(get=Mock(side_effect=AssertionError("must not call model")))
        c = ContextCompactor(context_window=128_000, scenario_llm_pool=pool)
        c._consecutive_failures = _MAX_CONSECUTIVE_FAILURES
        messages = _make_messages(30)

        result = await c.compact(messages)

        pool.get.assert_not_called()
        assert result.messages[1:] == messages[-9:]
        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_circuit_breaker_retries_after_cooldown(self) -> None:
        c = ContextCompactor(
            context_window=128_000,
            scenario_llm_pool=SimpleNamespace(),
        )
        c._consecutive_failures = _MAX_CONSECUTIVE_FAILURES
        c._circuit_opened_at = 100.0
        recovered = CompactionResult(
            compacted=True,
            messages=[{"role": "user", "content": "summary"}],
        )
        c._llm_compact = AsyncMock(return_value=recovered)  # type: ignore[method-assign]

        with patch(
            "magi.agent.execution.context_compactor.time.monotonic",
            return_value=100.0 + _CIRCUIT_RETRY_SECONDS,
        ):
            result = await c.compact(_make_messages(30))

        assert result is recovered
        c._llm_compact.assert_awaited_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Rule-based compaction
# ---------------------------------------------------------------------------


class TestRuleBasedCompact:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "window,count,compacted", [(32_000, 4, False), (32_000, 30, True), (200_000, 30, True)]
    )
    async def test_rule_fallback_preserves_exact_recent_history(self, window, count, compacted):
        c = ContextCompactor(context_window=window)
        messages = _make_messages(count)
        result = await c.compact(messages)
        assert result.compacted is compacted
        if compacted:
            assert result.messages[0]["role"] == "user"
            assert "[context truncated]" in result.messages[0]["content"]
            assert result.messages[1:] == messages[-9:]
        else:
            assert result.messages == messages
        assert result.original_message_count == count
        assert result.kept_message_count == len(result.messages)


    @pytest.mark.asyncio
    async def test_initial_history_fallback_retains_recent_exchanges_and_current_request(self):
        c = ContextCompactor(context_window=32_000)
        messages = [*_make_messages(30), {"role": "user", "content": "current request"}]
        result = await c.compact(messages, preserve_user_turns=True)
        assert result.compacted is True
        assert result.messages[1:] == messages[-9:]


    @pytest.mark.asyncio
    async def test_rule_fallback_keeps_every_retained_tool_result_with_its_call(self):
        compactor = ContextCompactor(context_window=32_000)
        messages = _make_round_messages(6)
        result = await compactor.compact(messages)
        assert result.compacted is True
        assert result.messages[1:] == [messages[0], *messages[-9:]]
        seen_calls = set()
        results = set()
        for message in result.messages:
            if message["role"] == "assistant":
                seen_calls.update(call["id"] for call in message.get("tool_calls", []))
            if message["role"] == "tool":
                assert message["tool_call_id"] in seen_calls
                results.add(message["tool_call_id"])
        assert results == seen_calls == {"tc_2", "tc_3", "tc_4", "tc_5"}

    @pytest.mark.asyncio
    async def test_rule_fallback_never_truncates_latest_user_message(self) -> None:
        compactor = ContextCompactor(context_window=32_000)
        compactor.record_input_tokens(30_000)
        current_request = "begin " + "x" * 120_000 + " end"
        messages = [
            {"role": "user", "content": current_request},
            {"role": "assistant", "content": "answer"},
        ]

        result = await compactor.compact(messages)

        assert result.compacted is True
        assert any(message.get("content") == current_request for message in result.messages)
        assert all("[truncated]" not in str(message.get("content")) for message in result.messages)
        assert result.messages[-1]["role"] == "assistant"
        assert compactor._last_input_tokens is None

    @pytest.mark.asyncio
    async def test_rule_fallback_drops_oversized_old_turn_as_a_whole(self) -> None:
        compactor = ContextCompactor(context_window=32_000)
        compactor.record_input_tokens(30_000)
        messages = [
            {"role": "user", "content": "old question " + "x" * 120_000},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current question"},
        ]

        result = await compactor.compact(messages, preserve_user_turns=True)

        assert result.messages[-1] == {"role": "user", "content": "current question"}
        assert all("old question" not in str(message.get("content")) for message in result.messages)
        assert all("old answer" not in str(message.get("content")) for message in result.messages)

    @pytest.mark.asyncio
    async def test_tool_round_fallback_keeps_latest_user_request_verbatim(self) -> None:
        compactor = ContextCompactor(context_window=32_000)
        current_request = "inspect the repository exactly as requested"
        messages: list[dict[str, Any]] = [{"role": "user", "content": current_request}]
        for index in range(6):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"call-{index}", "name": "demo"}],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": f"call-{index}",
                        "content": f"result-{index}",
                    },
                ]
            )

        result = await compactor.compact(messages)

        assert result.messages[1]["content"] == current_request
        assert [
            message.get("content")
            for message in result.messages
            if message.get("role") == "user" and message is not result.messages[0]
        ] == [current_request]

    @pytest.mark.asyncio
    async def test_rule_fallback_preserves_only_active_runtime_context(self) -> None:
        compactor = ContextCompactor(context_window=32_000)
        old_runtime = build_runtime_world_state_message("Local date: 2026-08-25")
        active_runtime = build_runtime_world_state_message("Local date: 2026-08-26")
        stale_working = build_working_context_message("stale private recall")
        active_working = build_working_context_message("active private recall")
        active_launch = build_launch_context_message("parent task snapshot")
        assert old_runtime and active_runtime and stale_working and active_working
        assert active_launch
        messages = [old_runtime, stale_working, {"role": "user", "content": "old request"}]
        messages.extend(_make_round_messages(rounds=5)[1:])
        messages.extend(
            [
                active_runtime,
                active_working,
                active_launch,
                {"role": "user", "content": "current"},
            ]
        )

        result = await compactor.compact(messages)

        contents = [str(message.get("content") or "") for message in result.messages]
        assert active_runtime["content"] in contents
        assert active_working["content"] in contents
        assert active_launch["content"] in contents
        assert old_runtime["content"] not in contents
        assert stale_working["content"] not in contents


# ---------------------------------------------------------------------------
# LLM-based compaction
# ---------------------------------------------------------------------------


class TestLLMCompact:
    @pytest.mark.asyncio
    async def test_llm_compact_success(self) -> None:
        fake_response = SimpleNamespace(content="Primary request: inspect the repository.")
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=fake_response)

        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(get=lambda scenario: fake_adapter)

        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        msgs = _make_round_messages(rounds=6)

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge", return_value=mock_bridge
        ):
            result = await c.compact(msgs, system_prompt="sys")

        assert result.compacted is True
        assert result.messages[0]["role"] == "user"
        assert "[context compacted]" in result.messages[0]["content"]
        assert "Primary request" in result.summary_text
        assert c._consecutive_failures == 0
        system_prompt = mock_bridge.chat.await_args.kwargs["system_prompt"]
        assert "one structured plain-text summary only" in system_prompt
        assert "<analysis>" not in system_prompt

    @pytest.mark.asyncio
    async def test_initial_history_summary_keeps_recent_user_turns_complete(self) -> None:
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="summary"))
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        compactor = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        messages = _make_messages(10)

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            result = await compactor.compact(messages, preserve_user_turns=True)

        assert result.compacted is True
        assert result.messages[1:] == messages[-6:]
        summary_prompt = mock_bridge.chat.await_args.kwargs["messages"][0]["content"]
        assert "user message 0" in summary_prompt
        assert "assistant reply 3" in summary_prompt
        assert "user message 4" not in summary_prompt

    @pytest.mark.asyncio
    async def test_llm_summary_retains_only_complete_rounds_that_fit_tail_budget(self) -> None:
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="summary"))
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        compactor = ContextCompactor(context_window=32_000, scenario_llm_pool=fake_pool)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "inspect"}]
        for index in range(5):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"call-{index}", "name": "demo"}],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": f"call-{index}",
                        "content": f"result-{index}-" + ("x" * 8_000),
                    },
                ]
            )

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            result = await compactor.compact(messages)

        assert result.compacted is True
        assert result.messages[1] is messages[0]
        assert result.messages[2:] == messages[-2:]
        summary_prompt = mock_bridge.chat.await_args.kwargs["messages"][0]["content"]
        assert "result-3" in summary_prompt
        assert "result-4" not in summary_prompt

    @pytest.mark.asyncio
    async def test_single_long_user_turn_keeps_its_tool_sequence_in_fallback(self) -> None:
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        compactor = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        messages: list[dict[str, Any]] = [{"role": "user", "content": "inspect"}]
        for index in range(6):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"call-{index}", "name": "demo"}],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": f"call-{index}",
                        "content": f"result-{index}",
                    },
                ]
            )

        result = await compactor.compact(messages, preserve_user_turns=True)

        assert result.messages[1:] == messages

    @pytest.mark.asyncio
    async def test_tool_round_summary_keeps_latest_user_request_verbatim(self) -> None:
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="summary"))
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        compactor = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        current_request = "inspect the repository exactly as requested"
        messages: list[dict[str, Any]] = [{"role": "user", "content": current_request}]
        for index in range(6):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"call-{index}", "name": "demo"}],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": f"call-{index}",
                        "content": f"result-{index}",
                    },
                ]
            )

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            result = await compactor.compact(messages)

        assert [
            message.get("content")
            for message in result.messages
            if message.get("content") == current_request
        ] == [current_request]
        summary_prompt = mock_bridge.chat.await_args.kwargs["messages"][0]["content"]
        assert current_request not in summary_prompt

    @pytest.mark.asyncio
    async def test_summary_never_absorbs_runtime_owned_context(self) -> None:
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="summary"))
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        compactor = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        runtime_state = build_runtime_world_state_message("Local date: 2026-08-26")
        working_context = build_working_context_message("private recalled context")
        launch_context = build_launch_context_message("parent task snapshot")
        assert runtime_state and working_context and launch_context
        messages: list[dict[str, Any]] = [
            runtime_state,
            working_context,
            launch_context,
            {"role": "user", "content": "inspect the repository"},
        ]
        for index in range(6):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": f"call-{index}", "name": "demo"}],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": f"call-{index}",
                        "content": f"result-{index}",
                    },
                ]
            )

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            result = await compactor.compact(messages)

        assert runtime_state in result.messages
        assert working_context in result.messages
        assert launch_context in result.messages
        summary_prompt = mock_bridge.chat.await_args.kwargs["messages"][0]["content"]
        assert runtime_state["content"] not in summary_prompt
        assert working_context["content"] not in summary_prompt
        assert launch_context["content"] not in summary_prompt

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rule_based(self) -> None:
        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(get=lambda scenario: fake_adapter)

        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        msgs = _make_round_messages(rounds=6)

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            side_effect=RuntimeError("boom"),
        ):
            result = await c.compact(msgs, system_prompt="sys")

        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]
        assert c._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_repeated_summary_failures_open_circuit_with_retry_timestamp(self) -> None:
        fake_pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        messages = _make_round_messages(rounds=6)

        with (
            patch.object(c, "_llm_compact", AsyncMock(side_effect=RuntimeError("boom"))),
            patch(
                "magi.agent.execution.context_compactor.time.monotonic",
                return_value=123.0,
            ),
        ):
            for _ in range(_MAX_CONSECUTIVE_FAILURES):
                await c.compact(messages)

        assert c._consecutive_failures == _MAX_CONSECUTIVE_FAILURES
        assert c._circuit_opened_at == 123.0

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
            summary = await compactor._call_summariser("x" * 120_000)

        assert summary == "final cumulative summary"
        assert mock_bridge.chat.await_count == 2
        second_prompt = mock_bridge.chat.await_args_list[1].kwargs["messages"][0]["content"]
        assert "partial summary" in second_prompt

    @pytest.mark.asyncio
    async def test_summary_output_budget_tracks_active_model_capacity(self) -> None:
        fake_adapter = SimpleNamespace()
        fake_pool = SimpleNamespace(
            resolve=lambda scenario: ResolvedModel(
                adapter=fake_adapter,
                context=ModelContextProfile(
                    provider_id="summary-provider",
                    model_id="large-summary-model",
                    context_window=1_000_000,
                    max_output_tokens=64_000,
                ),
            )
        )
        mock_bridge = AsyncMock()
        mock_bridge.chat = AsyncMock(return_value=SimpleNamespace(content="summary"))
        compactor = ContextCompactor(
            context_window=32_000,
            scenario_llm_pool=fake_pool,
        )

        with patch(
            "magi.agent.execution.context_compactor.LLMProviderBridge",
            return_value=mock_bridge,
        ):
            summary = await compactor._call_summariser("conversation")

        assert summary == "summary"
        assert mock_bridge.chat.await_args.kwargs["max_tokens"] == 1_190
        assert "within 1190 tokens" in mock_bridge.chat.await_args.kwargs["system_prompt"]

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

        mock_bridge.chat.assert_awaited_once()
        assert result.compacted is True
        assert "[context truncated]" in result.messages[0]["content"]
        assert result.messages[1:] == [messages[0], *messages[-9:]]
        assert result.summary_text == ""
        assert compactor._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_oversized_current_request_uses_lossless_fallback_without_summary(self) -> None:
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
        mock_bridge.chat.assert_not_awaited()
        assert "[context truncated]" in result.messages[0]["content"]
        assert result.messages[1:] == messages

    @pytest.mark.asyncio
    async def test_too_few_rounds_not_compacted(self) -> None:
        from unittest.mock import Mock

        fake_pool = SimpleNamespace(get=Mock(return_value=SimpleNamespace()))

        c = ContextCompactor(context_window=200_000, scenario_llm_pool=fake_pool)
        # Only 2 rounds → groups <= _KEEP_RECENT_ROUNDS, skip.
        msgs = _make_round_messages(rounds=2)

        result = await c.compact(msgs, system_prompt="sys")
        fake_pool.get.assert_not_called()
        assert result.compacted is False
        assert result.messages == msgs


# ---------------------------------------------------------------------------
# Render messages for summary
# ---------------------------------------------------------------------------


class TestRenderMessagesForSummary:
    def test_tool_result_is_not_truncated_again_before_summary(self) -> None:
        long_content = "result-start-" + ("x" * 3000) + "-result-end"
        msgs = [{"role": "tool", "tool_call_id": "t1", "content": long_content}]
        c = ContextCompactor()
        rendered = c._render_messages_for_summary(msgs)
        assert long_content in rendered
        assert "result-start" in rendered
        assert "result-end" in rendered

    def test_tool_call_input_is_not_truncated_again_before_summary(self) -> None:
        long_query = "query-start-" + ("x" * 1200) + "-query-end"
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "search",
                        "input": {"query": long_query},
                    }
                ],
            }
        ]
        c = ContextCompactor()

        rendered = c._render_messages_for_summary(msgs)

        assert long_query in rendered
        assert "query-start" in rendered
        assert "query-end" in rendered

    def test_openai_style_tool_call_is_included_in_summary_input(self) -> None:
        long_query = "query-start-" + ("x" * 1200) + "-query-end"
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "search",
                            "arguments": json.dumps({"query": long_query}),
                        },
                    }
                ],
            }
        ]
        c = ContextCompactor()

        rendered = c._render_messages_for_summary(msgs)

        assert "search" in rendered
        assert "call-1" in rendered
        assert long_query in rendered

    @pytest.mark.parametrize(
        "message,expected",
        [
            ({"role": "user", "content": "hello"}, "user: hello"),
            (
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "thinking"},
                        {"type": "tool_use", "name": "search", "input": {"q": "test"}},
                    ],
                },
                'assistant: thinking\n[call search({"q": "test"})]',
            ),
        ],
    )
    def test_summary_renderer_preserves_roles_text_and_tool_arguments(self, message, expected):
        assert ContextCompactor._render_messages_for_summary([message]) == expected


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestEventEmission:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("callback_kind", ["sync", "async", "raising"])
    async def test_real_compaction_emits_complete_events_and_survives_callback_failure(
        self, callback_kind, monkeypatch
    ):
        from magi.context.window_budget import estimate_context_tokens

        events = []

        def sync_callback(payload):
            events.append(payload)
            if callback_kind == "raising":
                raise ValueError("callback failed")

        async def async_callback(payload):
            events.append(payload)

        callback = async_callback if callback_kind == "async" else sync_callback
        bridge = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(content="summary")))
        pool = SimpleNamespace(get=lambda scenario: SimpleNamespace())
        monkeypatch.setattr(
            "magi.agent.execution.context_compactor.LLMProviderBridge", lambda adapter: bridge
        )
        monkeypatch.setattr("magi.agent.execution.context_compactor.time.monotonic", lambda: 100.0)
        c = ContextCompactor(context_window=200_000, scenario_llm_pool=pool, on_event=callback)
        messages = _make_round_messages(6)
        result = await c.compact(messages)
        bridge.chat.assert_awaited_once()
        assert result.compacted is True and result.summary_text == "summary"
        assert result.messages[1:] == [messages[0], *messages[-5:]]
        assert events == [
            {
                "stage": "context_compacting",
                "older_message_count": 8,
                "recent_message_count": 6,
                "estimated_tokens": estimate_context_tokens(messages[1:9]),
            },
            {
                "stage": "context_compacted",
                "original_count": 14,
                "compacted_count": 7,
                "summary_length": 7,
                "elapsed_ms": 0,
            },
        ]


# ---------------------------------------------------------------------------
# get_usage tests
# ---------------------------------------------------------------------------


class TestGetUsage:
    def test_usage_tracks_recorded_input_and_resets_between_runs(self):
        c = ContextCompactor(context_window=128_000)
        assert c.get_usage() is None
        for value in [0, -1]:
            c.record_input_tokens(value)
            assert c.get_usage() is None
        for value in [50_000, 30_000]:
            c.record_input_tokens(value)
            assert c.get_usage() == {
                "used_tokens": value,
                "context_window": 128_000,
                "window_size": 128_000,
                "input_capacity": 119_808,
                "compaction_threshold": 89_856,
                "threshold": 89_856,
            }
        c.record_input_tokens(0)
        assert c.get_usage()["used_tokens"] == 30_000
        c.begin_run()
        assert c.get_usage() is None
        assert c.should_compact([]) is False
