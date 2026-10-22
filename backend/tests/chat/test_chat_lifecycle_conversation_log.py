"""Lifecycle binds transcript and consumed dependencies to the same chat owner."""

from __future__ import annotations

from pathlib import Path

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.chat.conversation_log import ConversationLog
from magi.chat.lifecycle import ChatStoreModule
from magi.chat.storage.sqlite_store import SqliteChatRepository as ChatStore
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
        assert module._conversation_log._consumed is ctx.chat.store
        path = str(ctx.core.runtime_paths.chat_db_path)
        assert ctx.chat.store.db_path == path
        await module._conversation_log.record_consumed(
            session_id="session", run_id="run", revision=2, message_ids=["message"]
        )
        await module._conversation_log.record_consumed(
            session_id="other", run_id="unrelated", revision=1, message_ids=["message"]
        )
        assert await module._conversation_log.find_dependents(
            session_id="session", message_id="message"
        ) == [("run", 2)]
        reopened = ChatStore(db_path=path)
        await reopened.initialize()
        assert await reopened.find_runs_that_consumed(
            session_id="session", message_id="message"
        ) == [("run", 2)]
        assert await reopened.find_runs_that_consumed(session_id="other", message_id="message") == [
            ("unrelated", 1)
        ]
    finally:
        await module.shutdown()
