"""Unit tests for :mod:`magi.control.run_control` primitives."""
from __future__ import annotations

import asyncio

import pytest

from magi.control.run_control import (
    DetachRequested,
    DetachSignal,
    RunInputInbox,
    RunInputMessage,
)
from magi.agent.execution.checkpoint import AgentRunCheckpoint
from magi.agent.execution.evidence import ToolExecutionEvidence
from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningState


@pytest.mark.asyncio
async def test_input_queue_drains_fifo_without_replaying_consumed_messages():
    inbox = RunInputInbox()
    assert inbox.is_empty()
    messages = [
        RunInputMessage(content="first", reason="clarification", metadata={"id": 1}),
        RunInputMessage(content="second", metadata={"id": 2}),
    ]
    for message in messages:
        await inbox.push(message)
    assert not inbox.is_empty()
    assert await inbox.drain() == messages
    assert inbox.is_empty()
    assert await inbox.drain() == []
    later = RunInputMessage(content="later")
    await inbox.push(later)
    assert await inbox.drain() == [later]


@pytest.mark.asyncio
async def test_input_queue_concurrent_producers_do_not_lose_messages() -> None:
    inbox = RunInputInbox()

    async def push_batch(prefix: str, count: int) -> None:
        for i in range(count):
            await inbox.push(RunInputMessage(content=f"{prefix}-{i}"))

    await asyncio.gather(push_batch("a", 5), push_batch("b", 5))

    drained = await inbox.drain()
    assert len(drained) == 10
    assert {msg.content for msg in drained} == {
        *(f"a-{i}" for i in range(5)),
        *(f"b-{i}" for i in range(5)),
    }


@pytest.mark.asyncio
async def test_detach_signal_wakes_waiter_with_first_complete_payload():
    signal = DetachSignal()
    assert signal.is_requested() is False
    assert signal.payload is None
    waiter = asyncio.create_task(signal.wait())
    original = DetachRequested(reason="user_request", requested_by="operator", note="mid-flight")
    try:
        await asyncio.sleep(0)
        assert not waiter.done()
        signal.request(original)
        signal.request(DetachRequested(reason="later", note="must not replace"))
        assert await asyncio.wait_for(waiter, timeout=1) == original
        assert signal.is_requested() is True
        assert signal.payload == original
        assert await asyncio.wait_for(signal.wait(), timeout=1) == original
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


def _checkpoint() -> AgentRunCheckpoint:
    policy = ReasoningPolicy()
    return AgentRunCheckpoint(
        run_id="run-1",
        messages=[{"role": "user", "content": "hi"}],
        effective_system_prompt="system",
        tools=[{"type": "function", "function": {"name": "read"}}],
        iteration=3,
        reasoning_policy=policy,
        reasoning_state=ReasoningState.start(policy),
        selected_tool_names=["read"],
        tool_evidence=[
            ToolExecutionEvidence(
                tool_name="read",
                success=True,
                effect_class="read_only",
                replay_policy="safe",
            )
        ],
        reason="user_request",
        note="transfer",
    )


def test_agent_run_checkpoint_roundtrips_through_dict() -> None:
    snap = _checkpoint()
    restored = AgentRunCheckpoint.from_dict(snap.to_dict())
    assert restored.run_id == snap.run_id
    assert restored.messages == snap.messages
    assert restored.iteration == snap.iteration
    assert restored.tools == snap.tools
    assert restored.selected_tool_names == snap.selected_tool_names
    assert restored.tool_evidence[0].evidence_id == snap.tool_evidence[0].evidence_id
    assert restored.reason == snap.reason
    assert restored.note == snap.note


def test_agent_run_checkpoint_roundtrip_isolates_mutable_state() -> None:
    snap = _checkpoint()
    restored = AgentRunCheckpoint.from_dict(snap.to_dict())
    restored.messages[0]["content"] = "edited-again"
    restored.selected_tool_names.append("write")
    assert snap.messages[0]["content"] == "hi"
    assert snap.selected_tool_names == ["read"]
