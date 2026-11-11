"""A truncated generation may retry, but never advances tools or exceeds task limits."""

from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest

from magi.agent.execution.function_calling import llm
from magi.agent.execution.function_calling.llm_invocation import FunctionCallingLlmRequest
from magi.config.models import ThinkingDepth
from magi.llm.model_context import ModelContextProfile
from magi.llm.output_limit import OutputLimitReached
from magi.llm.provider_bridge import ProviderUsage
from magi.llm.cancellable_client import CancellationRaised
from magi.llm.stream_errors import IncompleteStreamError
from magi.control.cancel import EventCancelToken
from magi.control.run_control import null_run_control


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
    monkeypatch.setattr(llm, "reserve_task_llm_calls", budget)
    monkeypatch.setattr(llm, "emit_stream_event", events)
    original = request()

    async def invoke(attempt):
        attempts.append(attempt)
        if len(attempts) <= failures:
            raise OutputLimitReached(ProviderUsage(prompt_tokens=22_533,
                completion_tokens=attempt.max_tokens or 4_096, reasoning_tokens=4_096))
        return "complete"

    if failures < 3:
        assert await llm._call_with_generation_recovery(
            prepared(), original, control=None, tools=[], invoke=invoke,
        ) == "complete"
    else:
        with pytest.raises(OutputLimitReached):
            await llm._call_with_generation_recovery(
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
    monkeypatch.setattr(llm, "reserve_task_llm_calls", AsyncMock())
    invoke = AsyncMock(side_effect=[OutputLimitReached(ProviderUsage(
        prompt_tokens=input_tokens, completion_tokens=used)), "complete"])
    if expected is None:
        with pytest.raises(OutputLimitReached):
            await llm._call_with_generation_recovery(prepared(window, capacity), request(),
                control=None, tools=[], invoke=invoke)
        assert invoke.await_count == 1
    else:
        assert await llm._call_with_generation_recovery(prepared(window, capacity), request(),
            control=None, tools=[], invoke=invoke) == "complete"
        assert invoke.await_args.args[0].max_tokens == expected


@pytest.mark.asyncio
async def test_cancellation_and_budget_failure_stop_recovery(monkeypatch):
    invoke = AsyncMock(side_effect=OutputLimitReached(ProviderUsage(completion_tokens=4_096)))
    budget = AsyncMock(side_effect=RuntimeError("task budget exhausted"))
    monkeypatch.setattr(llm, "reserve_task_llm_calls", budget)
    with pytest.raises(RuntimeError, match="task budget exhausted"):
        await llm._call_with_generation_recovery(prepared(), request(), control=None, tools=[], invoke=invoke)
    assert invoke.await_count == 1
    monkeypatch.setattr(llm, "pre_poll_run_control", AsyncMock(side_effect=CancellationRaised("cancelled")))
    with pytest.raises(CancellationRaised):
        await llm._call_with_generation_recovery(prepared(), request(), control=None, tools=[], invoke=invoke)
    assert budget.await_count == 1


@pytest.mark.asyncio
async def test_missing_usage_does_not_guess_a_smaller_provider_default(monkeypatch):
    monkeypatch.setattr(llm, "reserve_task_llm_calls", AsyncMock())
    invoke = AsyncMock(side_effect=[OutputLimitReached(), "complete"])
    assert await llm._call_with_generation_recovery(prepared(), request(), control=None,
        tools=[], invoke=invoke) == "complete"
    assert invoke.await_args.args[0].max_tokens == 384_000


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.ReadError("connection closed"),
    httpx.ReadTimeout("read timed out"),
    httpx.RemoteProtocolError("incomplete chunk"),
    IncompleteStreamError("missing completion event"),
])
@pytest.mark.parametrize("final_response", [False, True])
async def test_stream_read_failure_retries_with_fresh_preview_and_budget(monkeypatch, error, final_response):
    events, reserved, consumed = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(llm.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(llm, "emit_stream_event", events)
    monkeypatch.setattr(llm, "reserve_task_llm_calls", reserved)
    monkeypatch.setattr(llm, "consume_task_llm_calls", consumed)
    original = replace(request(), request_kind="function_calling:final_response") if final_response else request()
    invoke = AsyncMock(side_effect=[error, "complete"])

    assert await llm._call_with_generation_recovery(
        prepared(), original, control=None, tools=[], invoke=invoke,
    ) == "complete"

    assert reserved.await_count == (0 if final_response else 1)
    assert consumed.await_count == (1 if final_response else 0)
    assert invoke.await_count == 2
    retried = invoke.await_args.args[0]
    assert retried.request_id != original.request_id
    assert retried.max_tokens is None
    assert retried.messages is original.messages
    assert events.await_args.args[0].kind == "text_reset"
    assert events.await_args.args[0].step_label == "stream_retry"


@pytest.mark.asyncio
async def test_stream_read_failure_stops_after_two_retries(monkeypatch):
    monkeypatch.setattr(llm.asyncio, "sleep", AsyncMock())
    invoke = AsyncMock(side_effect=IncompleteStreamError("missing completion event"))
    with pytest.raises(IncompleteStreamError):
        await llm._call_with_generation_recovery(
            prepared(), request(), control=None, tools=[], invoke=invoke,
        )
    assert invoke.await_count == 3


@pytest.mark.asyncio
async def test_retry_wait_observes_cancellation_before_spending_budget(monkeypatch):
    control = null_run_control()
    control.cancel_token = EventCancelToken()
    budget = AsyncMock()

    async def cancel_during_wait(_delay):
        control.cancel_token.cancel("stop retrying")

    monkeypatch.setattr(llm.asyncio, "sleep", cancel_during_wait)
    monkeypatch.setattr(llm, "reserve_task_llm_calls", budget)
    invoke = AsyncMock(side_effect=httpx.ReadTimeout("read timed out"))
    with pytest.raises(CancellationRaised):
        await llm._call_with_generation_recovery(
            prepared(), request(), control=control, tools=[], invoke=invoke,
        )
    assert invoke.await_count == 1
    budget.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_stream_retry_discards_partial_question_and_text(monkeypatch):
    from magi.agent.execution.function_calling.orchestrator import FunctionCallingOrchestrator
    from magi.agent.execution.task_budget import task_execution_budget_scope, prepay_task_llm_calls
    from magi.llm.openai import OpenAIAdapter
    from magi.llm.streaming_events import stream_scope

    async def broken_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content="Failed preview text that must be removed.",
            tool_calls=[SimpleNamespace(index=0, id="draft-question", function=SimpleNamespace(
                name="ask_user_question", arguments='{"question":"unfinished"}',
            ))],
        ), finish_reason=None)], usage=None)
        raise httpx.ReadError("stream disconnected")

    async def complete_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
            content="Recovered answer", tool_calls=None,
        ), finish_reason="stop")], usage=None)

    adapter = OpenAIAdapter.__new__(OpenAIAdapter)
    adapter._model, adapter._provider = "fake-model", "fake-provider"
    adapter._provider_plan = adapter._provider_instance_id = adapter._base_url = None
    create = AsyncMock(side_effect=[broken_stream(), complete_stream()])
    adapter._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    host = FunctionCallingOrchestrator(SimpleNamespace(), llm_adapter=adapter)
    host.provider_bridge._operations._emit_usage_event = AsyncMock()
    monkeypatch.setattr(llm.asyncio, "sleep", AsyncMock())
    events = []

    async def sink(event):
        events.append(event)

    async with task_execution_budget_scope(max_llm_calls=3) as budget:
        await prepay_task_llm_calls(2)
        async with stream_scope(sink, source="chat"):
            result = await host._call_llm_with_tools("system", [{"role": "user", "content": "hello"}], [
                {"type": "function", "function": {"name": "ask_user_question", "parameters": {"type": "object"}}},
            ])

    assert result["content"] == "Recovered answer"
    assert "tool_calls" not in result
    assert create.await_count == 2
    assert budget.llm_calls == 2
    assert any(event.kind == "tool_call_start" for event in events)
    assert not any(event.kind == "tool_call_end" for event in events)
    reset = next(index for index, event in enumerate(events) if event.kind == "text_reset")
    assert "".join(event.text or "" for event in events[reset + 1:] if event.kind == "text_delta") == "Recovered answer"
