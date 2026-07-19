"""Async serialization for managed chat asset and owner mutations."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar


@dataclass(slots=True)
class _AssetMutationLockState:
    lock: asyncio.Lock
    users: int = 0


_ASSET_MUTATION_STATE: _AssetMutationLockState | None = None
_ASSET_MUTATION_DEPTH: ContextVar[int] = ContextVar(
    "chat_asset_mutation_depth",
    default=0,
)

P = ParamSpec("P")
R = TypeVar("R")


def chat_asset_mutation_is_held() -> bool:
    """Return whether the current execution context owns the asset boundary."""

    return _ASSET_MUTATION_DEPTH.get() > 0


def require_chat_asset_mutation() -> None:
    """Reject managed asset mutation code that bypasses the shared boundary."""

    if not chat_asset_mutation_is_held():
        raise RuntimeError("Managed chat asset mutation boundary is required")


@asynccontextmanager
async def chat_asset_mutation() -> AsyncIterator[None]:
    """Serialize managed files, owner transactions, and garbage collection."""

    global _ASSET_MUTATION_STATE
    if chat_asset_mutation_is_held():
        raise RuntimeError("Managed chat asset mutation boundary must not be nested")
    state = _ASSET_MUTATION_STATE
    if state is None:
        state = _AssetMutationLockState(lock=asyncio.Lock())
        _ASSET_MUTATION_STATE = state
    state.users += 1
    acquired = False
    token = None
    try:
        await state.lock.acquire()
        acquired = True
        token = _ASSET_MUTATION_DEPTH.set(1)
        yield
    finally:
        if token is not None:
            _ASSET_MUTATION_DEPTH.reset(token)
        if acquired:
            state.lock.release()
        state.users -= 1
        if state.users == 0 and _ASSET_MUTATION_STATE is state:
            _ASSET_MUTATION_STATE = None


def chat_asset_mutation_guarded_if(
    argument_name: str,
    predicate: Callable[[Any], bool],
) -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    """Lock one async owner write only when its payload can claim assets."""

    def decorate(func: Callable[P, Any]) -> Callable[P, Any]:
        signature = inspect.signature(func)

        @wraps(func)
        async def guarded(*args: P.args, **kwargs: P.kwargs) -> Any:
            bound = signature.bind(*args, **kwargs)
            value = bound.arguments.get(argument_name)
            if not predicate(value):
                return await func(*args, **kwargs)
            async with chat_asset_mutation():
                return await func(*args, **kwargs)

        return guarded

    return decorate


async def run_chat_asset_mutation(
    func: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Run one blocking filesystem mutation under the async boundary."""

    async with chat_asset_mutation():
        worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # A running thread cannot be cancelled. Keep the boundary held until
            # it has actually stopped mutating managed files, then preserve the
            # caller's cancellation instead of exposing an unlocked background
            # mutation to garbage collection or ownership writers.
            try:
                await worker
            except BaseException:
                pass
            raise


__all__ = [
    "chat_asset_mutation",
    "chat_asset_mutation_guarded_if",
    "chat_asset_mutation_is_held",
    "require_chat_asset_mutation",
    "run_chat_asset_mutation",
]
