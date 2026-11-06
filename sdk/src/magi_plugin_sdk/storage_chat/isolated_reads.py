"""One read connection per invocation, drained before its session can close."""

import asyncio
import inspect
from typing import Any
from ..async_cleanup import finish_cleanup
from ..storage_ports.chat_reads import ChatStorageReads
from .host import ChatStorageHost
from .relational import ChatReadDatabase
from .relational_reader import RelationalChatReadRepository


class IsolatedChatReads:
    def __init__(self, database: ChatReadDatabase, host: ChatStorageHost) -> None:
        self.database, self.host = database, host

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or not callable(getattr(ChatStorageReads, name, None)):
            raise AttributeError(name)
        prototype = getattr(RelationalChatReadRepository, name)
        if inspect.iscoroutinefunction(prototype):
            async def call(**kwargs: Any) -> Any:
                reader = RelationalChatReadRepository(database=self.database, host=self.host)
                try:
                    return await getattr(reader, name)(**kwargs)
                finally:
                    await finish_cleanup(asyncio.to_thread(reader.close))
            return call
        def call(**kwargs: Any) -> Any:
            reader = RelationalChatReadRepository(database=self.database, host=self.host)
            try:
                return getattr(reader, name)(**kwargs)
            finally:
                reader.close()
        return call
