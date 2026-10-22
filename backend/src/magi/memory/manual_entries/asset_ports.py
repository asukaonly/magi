"""Storage-neutral image repository and asynchronous application boundary."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ParamSpec, Protocol, TypeVar

from ...core.async_cleanup import finish_cleanup


class ImageAssetRepository(Protocol):
    """Own content-addressed bytes; callers never receive backend file paths.

    Adapters may use blocking storage clients. Application I/O runs through
    ``asset_io`` so cancellation cannot release a clear barrier before a write
    finishes. References and MIME conversion belong to this repository.
    """

    def store_bytes(self, data: bytes, *, content_type: str) -> str: ...
    def resolve(self, asset_ref: str) -> tuple[bytes, str] | None: ...
    def has_asset(self, asset_ref: str) -> bool: ...
    def clear(self) -> int: ...


_P = ParamSpec("_P")
_T = TypeVar("_T")


async def asset_io(operation: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Keep storage work off the runtime loop and drain it before cancellation."""
    return await finish_cleanup(asyncio.to_thread(operation, *args, **kwargs))
