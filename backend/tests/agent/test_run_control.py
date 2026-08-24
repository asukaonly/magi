"""Unit tests for :mod:`magi.control.run_control` primitives."""
from __future__ import annotations

import asyncio

import pytest

from magi.control.run_control import (
    DetachRequested,
    DetachSignal,
    SteerInbox,
    SteerMessage,
)
from magi.agent.execution.checkpoint import AgentRunCheckpoint
from magi.agent.execution.evidence import ToolExecutionEvidence
from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningState


@pytest.mark.asyncio
async def test_steer_inbox_drain_returns_pushed_messages_in_order() -> None:
    inbox = SteerInbox()
    await inbox.push(SteerMessage(content="first"))
    await inbox.push(SteerMessage(content="second"))

    drained = await inbox.drain()

    assert [msg.content for msg in drained] == ["first", "second"]


@pytest.mark.asyncio
async def test_steer_inbox_drain_empties_the_queue() -> None:
    inbox = SteerInbox()
    await inbox.push(SteerMessage(content="only"))

    first = await inbox.drain()
    second = await inbox.drain()

    assert [msg.content for msg in first] == ["only"]
    assert second == []
    assert inbox.is_empty()


@pytest.mark.asyncio
async def test_steer_inbox_concurrent_producers_do_not_lose_messages() -> None:
    inbox = SteerInbox()

    async def push_batch(prefix: str, count: int) -> None:
        for i in range(count):
            await inbox.push(SteerMessage(content=f"{prefix}-{i}"))

    await asyncio.gather(push_batch("a", 5), push_batch("b", 5))

    drained = await inbox.drain()
    assert len(drained) == 10
    assert {msg.content for msg in drained} == {
        *(f"a-{i}" for i in range(5)),
        *(f"b-{i}" for i in range(5)),
    }


def test_detach_signal_starts_unrequested() -> None:
    signal = DetachSignal()
    assert signal.is_requested() is False
    assert signal.payload is None


def test_detach_signal_request_records_payload() -> None:
    signal = DetachSignal()
    signal.request(DetachRequested(reason="user_request", note="mid-flight"))

    assert signal.is_requested() is True
    assert signal.payload is not None
    assert signal.payload.reason == "user_request"
    assert signal.payload.note == "mid-flight"


def test_detach_signal_request_is_idempotent() -> None:
    signal = DetachSignal()
    signal.request(DetachRequested(reason="first"))
    signal.request(DetachRequested(reason="second"))

    assert signal.payload is not None
    assert signal.payload.reason == "first"


@pytest.mark.asyncio
async def test_detach_signal_wait_returns_payload() -> None:
    signal = DetachSignal()

    async def trigger() -> None:
        await asyncio.sleep(0)
        signal.request(DetachRequested(reason="user_request"))

    _, payload = await asyncio.gather(trigger(), signal.wait())
    assert payload.reason == "user_request"


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
