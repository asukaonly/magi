"""Shared-operation barrier used to make destructive clears exclusive."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from ..core.operation_barrier import AsyncOperationBarrier


OperationGuardFactory = Callable[[], Any]


@asynccontextmanager
async def optional_operation_guard(
    factory: OperationGuardFactory | None,
) -> AsyncIterator[None]:
    """Enter a bound operation guard, or act as a no-op for standalone stores."""
    if factory is None:
        yield
        return
    async with factory():
        yield


__all__ = [
    "AsyncOperationBarrier",
    "OperationGuardFactory",
    "optional_operation_guard",
]
