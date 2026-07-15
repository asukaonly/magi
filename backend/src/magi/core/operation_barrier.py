"""Fair shared/exclusive barrier for asynchronous runtime operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class AsyncOperationBarrier:
    """Allow concurrent operations while giving exclusive work fair admission."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active_operations = 0
        self._exclusive_active = False
        self._exclusive_waiters = 0
        self._operation_depths: dict[asyncio.Task[object], int] = {}

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[None]:
        """Enter one shared operation that exclusive work must await."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Operation guard requires an asyncio task")
        async with self._condition:
            depth = self._operation_depths.get(task, 0)
            if depth == 0:
                await self._condition.wait_for(
                    lambda: not self._exclusive_active and self._exclusive_waiters == 0
                )
                self._active_operations += 1
            self._operation_depths[task] = depth + 1
        try:
            yield
        finally:
            async with self._condition:
                depth = self._operation_depths[task] - 1
                if depth > 0:
                    self._operation_depths[task] = depth
                else:
                    del self._operation_depths[task]
                    self._active_operations -= 1
                    self._condition.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        """Block new shared work and wait for active work to finish."""
        async with self._condition:
            self._exclusive_waiters += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._exclusive_active and self._active_operations == 0
                )
                self._exclusive_active = True
            finally:
                self._exclusive_waiters -= 1
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._exclusive_active = False
                self._condition.notify_all()


__all__ = ["AsyncOperationBarrier"]
