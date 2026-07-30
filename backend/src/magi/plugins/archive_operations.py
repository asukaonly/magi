"""Bounded execution for plugin archive inspection and installation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import threading
from typing import Any, TypeVar

_ResultT = TypeVar("_ResultT")
_ARCHIVE_OPERATION_LOCK = threading.RLock()
_ARCHIVE_OPERATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="magi-plugin-archive",
)


def serialize_plugin_archive_operation(
    operation: Callable[..., _ResultT],
) -> Callable[..., _ResultT]:
    """Serialize synchronous archive work across all callers in this process."""

    @wraps(operation)
    def wrapped(*args: Any, **kwargs: Any) -> _ResultT:
        with _ARCHIVE_OPERATION_LOCK:
            return operation(*args, **kwargs)

    return wrapped


def _run_serialized(operation: Callable[[], _ResultT]) -> _ResultT:
    with _ARCHIVE_OPERATION_LOCK:
        return operation()


async def run_plugin_archive_operation(operation: Callable[[], _ResultT]) -> _ResultT:
    """Queue archive work on one dedicated worker without occupying the shared pool."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _ARCHIVE_OPERATION_EXECUTOR,
        _run_serialized,
        operation,
    )


__all__ = [
    "run_plugin_archive_operation",
    "serialize_plugin_archive_operation",
]
