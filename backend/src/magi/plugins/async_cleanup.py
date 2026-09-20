"""Retain ownership of asynchronous plugin cleanup during cancellation."""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

_Result = TypeVar("_Result")


async def finish_cleanup(operation: Awaitable[_Result]) -> _Result:
    """Defer repeated cancellation until the supplied cleanup has settled."""
    task = asyncio.ensure_future(operation)
    interrupted: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            interrupted = exc
    result = task.result()
    if interrupted is not None:
        raise interrupted
    return result
