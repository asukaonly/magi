"""Compose native SQLite adapters for the bundled storage contribution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from magi_plugin_sdk.storage import StorageCall, StorageOpen, StorageOpened, StorageResult
from magi_plugin_sdk.storage_dispatch import (
    RepositoryDispatcher, CHANNEL_REPOSITORY_CONTRACTS, CHANNEL_REPOSITORY_METHODS,
    EVENT_REPOSITORY_CONTRACTS, EVENT_REPOSITORY_METHODS, CHAT_REPOSITORY_CONTRACTS, CHAT_REPOSITORY_METHODS,
)
from magi_plugin_sdk.storage_transfer import SnapshotTransport
from magi_plugin_sdk.storage_models.channels import ChannelStorageSnapshot
from magi_plugin_sdk.storage_models.event_snapshot import EventStorageSnapshot
from magi_plugin_sdk.storage_models.chat_snapshot import ChatStorageSnapshot
from magi_plugin_sdk.storage_chat.relational_store import RelationalChatRepository
from magi_plugin_sdk.storage_chat.isolated_reads import IsolatedChatReads
from magi_plugin_sdk.storage_chat.snapshots import RelationalChatStateTransfer
from ..channels.binding_settings_store import ChannelBindingSettingsStore
from ..channels.receipts_store import DeliveryReceiptsStore
from ..channels.persistence.session_mappings import SqliteChannelSessionRepository
from ..channels.persistence.snapshots import SqliteChannelStateTransfer
from ..chat.storage.host import LocalChatStorageHost
from ..chat.storage.sqlite_database import SqliteChatDatabase, SqliteChatReadDatabase
from ..core.async_cleanup import finish_cleanup
from ..db.runner import MIGRATION_TARGETS, run_upgrade_head
from ..memory.l1.storage.events import SqliteMemoryEventRepository
from ..memory.l1.storage.snapshots import SqliteEventStateTransfer
from ..outreach.stores import OutreachOutboxStore, OutreachDeliveryLogStore
from ..utils.runtime import RuntimePaths


@dataclass
class SqliteStorageSession:
    dispatcher: RepositoryDispatcher
    snapshots: SnapshotTransport


class SqliteStorageProvider:
    target_identity = "local-sqlite-v1"

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.sessions: dict[str, SqliteStorageSession] = {}

    async def open(self, request: StorageOpen) -> StorageOpened:
        if len(self.sessions) >= 8:
            raise ValueError("Too many active SQLite storage sessions")
        target_name = {"channels": "channels", "memory_events": "l1", "chat": "chat"}[request.domain]
        target = next(value for value in MIGRATION_TARGETS if value.name == target_name)
        if request.migrate:
            await finish_cleanup(asyncio.to_thread(run_upgrade_head, self.paths, targets=(target,)))
        if not target.db_path(self.paths).exists():
            raise RuntimeError("Selected SQLite storage has not been initialized")
        if request.domain == "channels":
            path = str(self.paths.channels_db_path)
            repositories = {
                "sessions": SqliteChannelSessionRepository(path), "receipts": DeliveryReceiptsStore(db_path=path),
                "binding_settings": ChannelBindingSettingsStore(db_path=path),
                "outbox": OutreachOutboxStore(db_path=path), "delivery_log": OutreachDeliveryLogStore(db_path=path),
            }
            methods, contracts = CHANNEL_REPOSITORY_METHODS, CHANNEL_REPOSITORY_CONTRACTS
            transfer, snapshot = SqliteChannelStateTransfer(path), ChannelStorageSnapshot
        elif request.domain == "memory_events":
            path = str(self.paths.l1_memory_db_path)
            repositories = {"events": SqliteMemoryEventRepository(path)}
            methods, contracts = EVENT_REPOSITORY_METHODS, EVENT_REPOSITORY_CONTRACTS
            transfer, snapshot = SqliteEventStateTransfer(path), EventStorageSnapshot
        else:
            writes = SqliteChatDatabase(self.paths.chat_db_path)
            reads = SqliteChatReadDatabase(self.paths.chat_db_path)
            host = LocalChatStorageHost(self.paths)
            repositories = {"chat": RelationalChatRepository(database=writes, host=host),
                            "reads": IsolatedChatReads(reads, host)}
            methods, contracts = CHAT_REPOSITORY_METHODS, CHAT_REPOSITORY_CONTRACTS
            transfer, snapshot = RelationalChatStateTransfer(writes), ChatStorageSnapshot
        dispatcher = RepositoryDispatcher(repositories, methods, contracts)
        from ..core.sqlite import sqlite_connection_async
        async with sqlite_connection_async(target.db_path(self.paths)) as db:
            row = await (await db.execute("SELECT version_num FROM alembic_version")).fetchone()
            if row is None:
                raise RuntimeError("SQLite schema revision is missing")
            version = str(row[0])
        identifier = uuid4().hex
        self.sessions[identifier] = SqliteStorageSession(dispatcher, SnapshotTransport(transfer, snapshot))
        return StorageOpened(session_id=identifier, target_identity=self.target_identity, schema_version=version)

    async def invoke(self, request: StorageCall) -> StorageResult:
        session = self.sessions.get(request.session_id)
        if session is None:
            return StorageResult(error="invalid")
        if request.repository == "transfer":
            return await session.snapshots.invoke(request)
        return await session.dispatcher.invoke(request)

    async def invoke_with_host(self, request: StorageCall, handler: Callable[..., Any]) -> StorageResult:
        return await self.invoke(request)

    def invoke_sync_with_host(self, request: StorageCall, handler: Callable[..., Any]) -> StorageResult:
        return asyncio.run(self.invoke(request))

    async def close(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session is not None:
            session.snapshots.close()

    async def shutdown(self) -> None:
        for session_id in tuple(self.sessions):
            await self.close(session_id)
