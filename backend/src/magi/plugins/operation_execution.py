"""Bounded execution lanes for plugin installation and runtime callbacks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import wraps
import threading
from typing import Any, Iterator, TypeVar

_ResultT = TypeVar("_ResultT")
MAX_CONCURRENT_PLUGIN_PREPARATIONS = 2
_ARCHIVE_OPERATION_LOCK = threading.RLock()
_ARCHIVE_OPERATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="magi-plugin-archive",
)
_PLUGIN_PREPARATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_PLUGIN_PREPARATIONS,
    thread_name_prefix="magi-plugin-prepare",
)
_PLUGIN_LIFECYCLE_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="magi-plugin-lifecycle",
)
_PLUGIN_CALLBACK_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="magi-plugin-callback",
)
_PLUGIN_PREPARATION_GATE = threading.BoundedSemaphore(MAX_CONCURRENT_PLUGIN_PREPARATIONS)
_PLUGIN_PREPARATION_LOCAL = threading.local()


def serialize_plugin_archive_operation(
    operation: Callable[..., _ResultT],
) -> Callable[..., _ResultT]:
    """Serialize synchronous archive work across all callers in this process."""

    @wraps(operation)
    def wrapped(*args: Any, **kwargs: Any) -> _ResultT:
        with _ARCHIVE_OPERATION_LOCK:
            with plugin_preparation_slot():
                return operation(*args, **kwargs)

    return wrapped


def _run_serialized(operation: Callable[[], _ResultT]) -> _ResultT:
    with _ARCHIVE_OPERATION_LOCK:
        with plugin_preparation_slot():
            return operation()


async def run_plugin_archive_operation(operation: Callable[[], _ResultT]) -> _ResultT:
    """Queue archive work on one dedicated worker without occupying the shared pool."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _ARCHIVE_OPERATION_EXECUTOR,
        _run_serialized,
        operation,
    )


@contextmanager
def plugin_preparation_slot() -> Iterator[None]:
    """Bound expensive package preparation across every synchronous caller."""

    depth = getattr(_PLUGIN_PREPARATION_LOCAL, "depth", 0)
    if depth == 0:
        _PLUGIN_PREPARATION_GATE.acquire()
    _PLUGIN_PREPARATION_LOCAL.depth = depth + 1
    try:
        yield
    finally:
        next_depth = _PLUGIN_PREPARATION_LOCAL.depth - 1
        _PLUGIN_PREPARATION_LOCAL.depth = next_depth
        if next_depth == 0:
            _PLUGIN_PREPARATION_GATE.release()


def _run_preparation(operation: Callable[[], _ResultT]) -> _ResultT:
    with plugin_preparation_slot():
        return operation()


async def run_plugin_preparation_operation(
    operation: Callable[[], _ResultT],
) -> _ResultT:
    """Run bounded package preparation without occupying the shared pool."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _PLUGIN_PREPARATION_EXECUTOR,
        _run_preparation,
        operation,
    )


async def run_plugin_lifecycle_operation(
    operation: Callable[[], _ResultT],
) -> _ResultT:
    """Run a lifecycle mutation on one dedicated worker."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _PLUGIN_LIFECYCLE_EXECUTOR,
        operation,
    )


async def run_plugin_callback_operation(
    operation: Callable[[], _ResultT],
) -> _ResultT:
    """Run untrusted synchronous plugin callbacks outside the event loop."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _PLUGIN_CALLBACK_EXECUTOR,
        operation,
    )


__all__ = [
    "MAX_CONCURRENT_PLUGIN_PREPARATIONS",
    "plugin_preparation_slot",
    "run_plugin_archive_operation",
    "run_plugin_callback_operation",
    "run_plugin_lifecycle_operation",
    "run_plugin_preparation_operation",
    "serialize_plugin_archive_operation",
]
