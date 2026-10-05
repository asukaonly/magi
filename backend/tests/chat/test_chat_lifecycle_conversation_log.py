"""Tests for ChatStoreModule constructing the ConversationLog (Phase F, Task 6).

ChatStoreModule.init() must wire up the ChatRunConsumedEventsStore alongside
the ChatStore and expose a ready-to-use ConversationLog so downstream
consumers (ChatTaskAgent → ChatContextAssembler) can resolve it via the
runtime bootstrap context.

Mirrors the pattern from
``backend/tests/channels/test_lifecycle_chat_sse_registration.py``:
construct the lifecycle module with a stubbed RuntimeBootstrapContext
sufficient for ``init()`` to run, then assert the conversation log is
present and properly wired.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.chat.conversation_log import ChatRunConsumedEventsStore, ConversationLog
from magi.chat.lifecycle import ChatStoreModule
from magi.chat.store import ChatStore
from magi.utils.runtime import RuntimePaths


def _build_ctx(tmp_path: Path) -> RuntimeBootstrapContext:
    ctx = RuntimeBootstrapContext()
    ctx.core.runtime_paths = RuntimePaths(base_dir=tmp_path)
    return ctx


@pytest.mark.asyncio
async def test_lifecycle_wires_durable_chat_dependency_log(tmp_path):
    ctx = _build_ctx(tmp_path)
    module = ChatStoreModule(ctx)
    try:
        await module.init()
        assert isinstance(ctx.chat.store, ChatStore)
        assert isinstance(module._conversation_log, ConversationLog)
        assert isinstance(module._consumed_events_store, ChatRunConsumedEventsStore)
        path = str(ctx.core.runtime_paths.chat_db_path)
        assert ctx.chat.store.db_path == module._consumed_events_store._db_path == path
        await module._conversation_log.record_consumed(
            session_id="session", run_id="run", revision=2, message_ids=["message"]
        )
        await module._conversation_log.record_consumed(
            session_id="other", run_id="unrelated", revision=1, message_ids=["message"]
        )
        assert await module._conversation_log.find_dependents(
            session_id="session", message_id="message"
        ) == [("run", 2)]
        reopened = ChatRunConsumedEventsStore(db_path=path)
        await reopened.initialize()
        assert await reopened.find_runs_that_consumed(
            session_id="session", message_id="message"
        ) == [("run", 2)]
        assert await reopened.find_runs_that_consumed(session_id="other", message_id="message") == [
            ("unrelated", 1)
        ]
    finally:
        await module.shutdown()
