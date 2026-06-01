"""Phase F Task 8: ChatHistoryService dual-writes appends to ConversationLog.

When a ``ConversationLog`` is wired into ``ChatHistoryService``, every call
to ``append_user_message`` / ``append_assistant_message`` must fire-and-forget
a typed ``ConversationEvent`` to the log. Failures in the log write must
never break the in-memory cache mutation (best-effort dual-write).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from magi.agent.task_agents.chat.history_service import ChatHistoryService
from magi_plugin_sdk.conversation import ConversationEvent


class _RecordingLog:
    """Records every append call so the test can assert on event shape."""

    def __init__(self) -> None:
        self.appends: list[tuple[ConversationEvent, str]] = []

    async def append(self, event, *, session_id):
        self.appends.append((event, session_id))


class _BrokenLog:
    async def append(self, *args, **kwargs):
        raise RuntimeError("storage offline")


def _build_service(tmp_path: Path, *, log=None) -> ChatHistoryService:
    """Construct a minimal ChatHistoryService for unit testing.

    Mirrors the pattern from
    ``test_chat_task_agent_orchestration.test_chat_history_service_uses_explicit_session_pairs_without_state_file``
    — only paths + the conversation_log are needed for the append paths."""
    return ChatHistoryService(
        l1_db_path=tmp_path / "l1.sqlite3",
        runtime_trace_db_path=tmp_path / "runtime_trace.sqlite3",
        conversation_log=log,
    )


@pytest.mark.asyncio
async def test_append_user_message_writes_user_event_to_log(tmp_path: Path) -> None:
    log = _RecordingLog()
    service = _build_service(tmp_path, log=log)
    # history_key format is user_id::session_id
    service.append_user_message("u-1::s-1", "hello")
    # The async write is fire-and-forget — yield once so the task runs
    await asyncio.sleep(0)
    assert len(log.appends) == 1
    event, session_id = log.appends[0]
    assert event.event_type == "user_message"
    assert event.content is not None
    assert event.content[0].text == "hello"
    assert event.actor == "u-1"
    assert session_id == "s-1"


@pytest.mark.asyncio
async def test_append_assistant_message_writes_agent_reply_event(tmp_path: Path) -> None:
    log = _RecordingLog()
    service = _build_service(tmp_path, log=log)
    service.append_assistant_message("u-1::s-1", "hi back")
    await asyncio.sleep(0)
    assert len(log.appends) == 1
    event, session_id = log.appends[0]
    assert event.event_type == "agent_reply"
    assert event.content is not None
    assert event.content[0].text == "hi back"
    assert session_id == "s-1"


@pytest.mark.asyncio
async def test_append_works_when_no_conversation_log_wired(tmp_path: Path) -> None:
    """Backward compat: when conversation_log=None, append still works
    and writes nothing to the log (no AttributeError)."""
    service = _build_service(tmp_path, log=None)
    # Should NOT raise
    service.append_user_message("u-1::s-1", "hello")
    service.append_assistant_message("u-1::s-1", "world")
    # In-memory state still has both messages
    history = service.get_history("u-1", "s-1")
    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


@pytest.mark.asyncio
async def test_log_append_failure_does_not_break_message_append(tmp_path: Path) -> None:
    """A failing log.append must not propagate — the in-memory cache
    still gets the message."""
    service = _build_service(tmp_path, log=_BrokenLog())
    # Should NOT raise
    service.append_user_message("u-1::s-1", "hello")
    # Allow fire-and-forget task to run (and swallow its error)
    await asyncio.sleep(0)
    # In-memory state still has the message
    history = service.get_history("u-1", "s-1")
    assert any(
        isinstance(m, dict) and m.get("content") == "hello"
        for m in history
    )
