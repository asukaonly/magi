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
async def test_chat_store_module_constructs_conversation_log(tmp_path):
    ctx = _build_ctx(tmp_path)
    module = ChatStoreModule(ctx)
    try:
        await module.init()
        assert ctx.chat.store is not None
        assert isinstance(ctx.chat.store, ChatStore)
        assert module._conversation_log is not None
        assert isinstance(module._conversation_log, ConversationLog)
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_chat_store_module_exposes_consumed_events_store(tmp_path):
    ctx = _build_ctx(tmp_path)
    module = ChatStoreModule(ctx)
    try:
        await module.init()
        assert isinstance(module._consumed_events_store, ChatRunConsumedEventsStore)
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_chat_store_module_conversation_log_uses_chat_db_path(tmp_path):
    """The consumed-events store should sit alongside the chat store on the
    same DB file so the chat-domain Alembic migrations own both tables."""
    ctx = _build_ctx(tmp_path)
    module = ChatStoreModule(ctx)
    try:
        await module.init()
        expected_db_path = str(ctx.core.runtime_paths.chat_db_path)
        # ChatRunConsumedEventsStore stores ``_db_path`` as a str of the
        # expanded path; ChatStore stores ``db_path`` likewise.
        assert module._consumed_events_store._db_path == expected_db_path
        assert ctx.chat.store.db_path == expected_db_path
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_chat_store_module_init_state_before_start(tmp_path):
    """Before init(), the conversation log attributes must be None so the
    resolver in ChatTaskAgent can short-circuit on missing wiring."""
    ctx = _build_ctx(tmp_path)
    module = ChatStoreModule(ctx)
    assert module._conversation_log is None
    assert module._consumed_events_store is None
