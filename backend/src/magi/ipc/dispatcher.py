"""IPC method dispatcher — routes method names to handler coroutines."""

from __future__ import annotations

import structlog
from typing import Any, Callable, Awaitable

from magi.ipc.protocol import IpcRequest, IpcNotify

logger = structlog.get_logger(__name__)

# Handler type: async (params) -> result_value
Handler = Callable[[dict[str, Any] | None], Awaitable[Any]]


class Dispatcher:
    """Registry of method → handler mappings."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    async def dispatch_request(self, req: IpcRequest) -> Any:
        handler = self._handlers.get(req.method)
        if handler is None:
            raise MethodNotFound(req.method)
        return await handler(req.params)

    async def dispatch_notify(self, notify: IpcNotify) -> None:
        handler = self._handlers.get(notify.method)
        if handler is None:
            logger.warning("ipc_notify_no_handler", method=notify.method)
            return
        try:
            await handler(notify.params)
        except Exception:
            logger.exception("ipc_notify_handler_error", method=notify.method)


class MethodNotFound(Exception):
    def __init__(self, method: str) -> None:
        self.method = method
        super().__init__(f"IPC method not found: {method}")
