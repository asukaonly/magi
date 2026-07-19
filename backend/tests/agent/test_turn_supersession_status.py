"""Tests for chat turn supersession status semantics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.chat import ChatTurnRecord
from magi.chat.task_agent.postprocess.trace_runtime import (
    ChatPostprocessRuntimeTraceMixin,
)
from magi.chat.task_agent.postprocess.turn_writes import ChatTurnStateWriter
from magi.chat.task_agent.session_run_decisions import (
    supersession_terminal_status,
)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("augment", "merged"),
        ("steer", "merged"),
        ("interrupt", "interrupted"),
    ],
)
def test_supersession_terminal_status(reason: str, expected: str) -> None:
    assert supersession_terminal_status(reason) == expected


@pytest.mark.asyncio
async def test_steer_persists_as_merge_in_chat_and_trace() -> None:
    original = ChatTurnRecord(
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        trace_id=None,
        orchestration_id=None,
        status="running",
        response_mode="final_only",
        execution_mode=None,
        ux_plan_json="{}",
        created_at_ms=100,
        updated_at_ms=100,
        completed_at_ms=None,
        error_text=None,
    )

    class _Store:
        saved: ChatTurnRecord | None = None

        async def get_turn(self, turn_id: str) -> ChatTurnRecord | None:
            return original if turn_id == original.turn_id else None

        async def upsert_turn(self, turn: ChatTurnRecord) -> None:
            self.saved = turn

    store = _Store()
    writer = ChatTurnStateWriter(
        chat_store=store,  # type: ignore[arg-type]
        trace_id_factory=lambda turn_id: f"trace:{turn_id}",
    )
    await writer.persist_turn_supersession(
        turn_id="turn-1",
        anchor_turn_id="turn-2",
        reason="steer",
        updated_at_ms=200,
    )

    assert store.saved is not None
    assert store.saved.status == "merged"
    assert store.saved.supersession_reason == "merged"

    trace_mixin = ChatPostprocessRuntimeTraceMixin()
    context = trace_mixin._trace_supersession_context(
        existing_turn=SimpleNamespace(started_at_ms=100),
        anchor_turn_id="turn-2",
        reason="steer",
        updated_at_ms=200,
    )
    assert context.status == "merged"
