from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List, Optional

import pytest
from agent.agent_run_helpers import run_agent

from magi.agent.execution.function_calling import (
    FunctionCallingOrchestrator,
    ToolCall,
    ToolCallResult,
)
from magi.llm.base import LLMAdapter
from magi.runtime_trace.store import RuntimeTraceStore
from magi.agent.turn_input import UserTurnInput


class _DummyLLMAdapter(LLMAdapter):
    def __init__(self) -> None:
        self._model = "dummy-model"

    async def generate(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        _ = (prompt, max_tokens, temperature, kwargs)
        return ""

    async def generate_stream(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        _ = (prompt, max_tokens, temperature, kwargs)
        if False:
            yield ""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> str:
        _ = (messages, max_tokens, temperature, kwargs)
        return ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        **kwargs,
    ) -> AsyncIterator[str]:
        _ = (messages, max_tokens, temperature, kwargs)
        if False:
            yield ""

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"


class _DummyToolRegistry:
    def is_skill(self, name: str) -> bool:
        _ = name
        return False

    def get_tool_info(self, name: str) -> dict[str, Any] | None:
        return {
            "name": name,
            "description": "test tool",
            "parameters": [],
        }

    def get_tool(self, name: str) -> Any:
        schema = SimpleNamespace(
            name=name,
            effect_class="read_only",
            effect_replay_policy="read_only",
            dangerous=False,
            requires_auth=False,
            metadata={},
        )
        return SimpleNamespace(get_schema=lambda: schema)


@pytest.fixture
async def runtime_trace_store(runtime_paths_with_schema):
    store = RuntimeTraceStore(
        db_path=str(runtime_paths_with_schema.runtime_trace_db_path)
    )
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_execute_with_tools_persists_iteration_llm_and_tool_rows(
    runtime_trace_store: RuntimeTraceStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = FunctionCallingOrchestrator(
        llm_adapter=_DummyLLMAdapter(),
        tool_registry=_DummyToolRegistry(),  # type: ignore[arg-type]
        runtime_trace_store=runtime_trace_store,
    )
    llm_responses = [
        {
            "tool_calls": [
                ToolCall(
                    id="call-1",
                    name="web-search",
                    arguments={"query": "Hangzhou news"},
                )
            ],
            "llm_trace": {
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 120,
                "output_tokens": 28,
                "duration_ms": 840,
            },
        },
        {
            "content": "final answer",
            "llm_trace": {
                "provider": "openai",
                "model": "gpt-test",
                "input_tokens": 64,
                "output_tokens": 18,
                "duration_ms": 320,
            },
        },
    ]

    async def _fake_call_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return llm_responses.pop(0)

    async def _fake_execute_tool_call(**kwargs):  # type: ignore[no-untyped-def]
        tool_call = kwargs["tool_call"]
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=True,
            data={"headline": "ok"},
            execution_time=0.25,
        )

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", _fake_call_llm_with_tools)
    monkeypatch.setattr(orchestrator, "_execute_tool_call", _fake_execute_tool_call)

    outcome = await run_agent(orchestrator,
        turn=UserTurnInput(text="search Hangzhou news", attachments=[], user_id=None, session_id=None),
        system_prompt="You are helpful.",
        selected_tools=["web-search"],
        user_id="local_user",
        session_id="session-1",
        turn_id="turn-1",
        conversation_history=[],
        intent="news_query",
        execution_agent_id="chat:local_user",
    )

    iteration_one = await runtime_trace_store.get_span("turn-1:iteration:1")
    iteration_two = await runtime_trace_store.get_span("turn-1:iteration:2")
    tool_request_llm = await runtime_trace_store.get_llm_call("turn-1:llm_call:llm_requested_tools:1")
    final_llm = await runtime_trace_store.get_llm_call("turn-1:llm_call:final_response:2")
    tool_span = await runtime_trace_store.get_span("turn-1:tool_call:1:call-1")
    tool_call = await runtime_trace_store.get_tool_call("turn-1:tool_call:1:call-1")

    assert outcome.status == "completed"
    assert outcome.content == "final answer"
    assert iteration_one is not None
    assert iteration_one.node_type == "iteration"
    assert iteration_one.status == "completed"
    assert iteration_two is not None
    assert iteration_two.status == "completed"
    # D phase 4: function-calling no longer persists trace_llm_calls rows
    # directly; the canonical llm_call SpanCompleted now flows from
    # provider_bridge on real LLM calls (mocked away here).
    assert tool_request_llm is None
    assert final_llm is None
    assert tool_span is not None
    assert tool_span.node_type == "tool_call"
    assert tool_call is not None
    assert tool_call.tool_name == "web-search"
    assert tool_call.success is True
