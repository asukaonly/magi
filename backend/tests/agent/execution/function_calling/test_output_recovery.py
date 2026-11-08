"""A truncated generation may retry, but never advances tools or exceeds task limits."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.agent.execution.function_calling import llm
from magi.agent.execution.function_calling.llm_invocation import FunctionCallingLlmRequest
from magi.config.models import ThinkingDepth
from magi.llm.model_context import ModelContextProfile
from magi.llm.output_limit import OutputLimitReached
from magi.llm.provider_bridge import ProviderUsage
from magi.llm.cancellable_client import CancellationRaised


def prepared(window=1_000_000, limit=384_000):
    profile = ModelContextProfile("deepseek", "deepseek-flash", window, limit)
    return llm._PreparedLlmCall(SimpleNamespace(_active_model_context=profile), "initial", 0, None)


def request():
    return FunctionCallingLlmRequest(
        "initial", "function_calling:chat_tools", "system",
        [{"role": "user", "content": "review this document"}], ThinkingDepth.HIGH,
        None, "session", "turn", "chat_agent", "chat", 1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [1, 2, 3])
async def test_output_recovery_is_bounded_and_counts_every_retry(monkeypatch, failures):
    attempts = []
    events = AsyncMock()
    budget = AsyncMock()
    monkeypatch.setattr(llm, "consume_task_llm_calls", budget)
    monkeypatch.setattr(llm, "emit_stream_event", events)
    original = request()

    async def invoke(attempt):
        attempts.append(attempt)
        if len(attempts) <= failures:
            raise OutputLimitReached(ProviderUsage(prompt_tokens=22_533,
                completion_tokens=attempt.max_tokens or 4_096, reasoning_tokens=4_096))
        return "complete"

    if failures < 3:
        assert await llm._call_with_output_recovery(
            prepared(), original, control=None, tools=[], invoke=invoke,
        ) == "complete"
    else:
        with pytest.raises(OutputLimitReached):
            await llm._call_with_output_recovery(
                prepared(), original, control=None, tools=[], invoke=invoke,
            )
    assert [a.max_tokens for a in attempts] == [None, 65_536, 131_072][:len(attempts)]
    assert all(a.messages is original.messages for a in attempts)
    assert len({a.request_id for a in attempts}) == len(attempts)
    assert budget.await_count == events.await_count == min(failures, 2)
    assert all(call.args[0].kind == "text_reset" for call in events.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("window,capacity,input_tokens,used,expected", [
    (1_000_000, 8_192, 20_000, 4_096, 8_192),
    (32_000, 24_000, 20_000, 8_192, 10_976),
    (32_000, 24_000, 24_000, 8_192, None),
    (1_000_000, 4_096, 20_000, 4_096, None),
])
async def test_recovery_respects_model_capacity_and_remaining_context(
    monkeypatch, window, capacity, input_tokens, used, expected,
):
    monkeypatch.setattr(llm, "consume_task_llm_calls", AsyncMock())
    invoke = AsyncMock(side_effect=[OutputLimitReached(ProviderUsage(
        prompt_tokens=input_tokens, completion_tokens=used)), "complete"])
    if expected is None:
        with pytest.raises(OutputLimitReached):
            await llm._call_with_output_recovery(prepared(window, capacity), request(),
                control=None, tools=[], invoke=invoke)
        assert invoke.await_count == 1
    else:
        assert await llm._call_with_output_recovery(prepared(window, capacity), request(),
            control=None, tools=[], invoke=invoke) == "complete"
        assert invoke.await_args.args[0].max_tokens == expected


@pytest.mark.asyncio
async def test_cancellation_and_budget_failure_stop_recovery(monkeypatch):
    invoke = AsyncMock(side_effect=OutputLimitReached(ProviderUsage(completion_tokens=4_096)))
    budget = AsyncMock(side_effect=RuntimeError("task budget exhausted"))
    monkeypatch.setattr(llm, "consume_task_llm_calls", budget)
    with pytest.raises(RuntimeError, match="task budget exhausted"):
        await llm._call_with_output_recovery(prepared(), request(), control=None, tools=[], invoke=invoke)
    assert invoke.await_count == 1
    monkeypatch.setattr(llm, "pre_poll_run_control", AsyncMock(side_effect=CancellationRaised("cancelled")))
    with pytest.raises(CancellationRaised):
        await llm._call_with_output_recovery(prepared(), request(), control=None, tools=[], invoke=invoke)
    assert budget.await_count == 1


@pytest.mark.asyncio
async def test_missing_usage_does_not_guess_a_smaller_provider_default(monkeypatch):
    monkeypatch.setattr(llm, "consume_task_llm_calls", AsyncMock())
    invoke = AsyncMock(side_effect=[OutputLimitReached(), "complete"])
    assert await llm._call_with_output_recovery(prepared(), request(), control=None,
        tools=[], invoke=invoke) == "complete"
    assert invoke.await_args.args[0].max_tokens == 384_000
