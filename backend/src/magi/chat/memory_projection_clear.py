"""Shared destructive-clear boundary for chat-to-memory recovery work."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ..core.operation_barrier import AsyncOperationBarrier


class ChatMemoryProjectionClearBoundaryCrossed(RuntimeError):
    """Raised when recovery work belongs to an older full-clear generation."""


@dataclass(frozen=True, slots=True)
class ChatMemoryProjectionAdmission:
    """Generation snapshot captured before one recovery read or claim."""

    local_generation: int
    clear_generation: int


class ChatMemoryProjectionClearLifecycle:
    """Fence assistant and user-turn memory recovery across a full clear."""

    def __init__(
        self,
        *,
        read_current_clear_generation: Callable[[], Awaitable[int]],
    ) -> None:
        if not callable(read_current_clear_generation):
            raise TypeError("Clear generation reader must be callable")
        self._read_current_clear_generation = read_current_clear_generation
        self._barrier = AsyncOperationBarrier()
        self._local_generation = 0
        self._clear_request_count = 0

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[ChatMemoryProjectionAdmission]:
        """Admit one complete recovery pass from read or claim through settlement."""

        async with self._barrier.operation():
            admission = ChatMemoryProjectionAdmission(
                local_generation=self._local_generation,
                clear_generation=self._normalize_clear_generation(
                    await self._read_current_clear_generation()
                ),
            )
            await self.ensure_current(admission)
            yield admission

    async def ensure_current(
        self,
        admission: ChatMemoryProjectionAdmission,
    ) -> None:
        """Reject work if either the local fence or durable generation advanced."""

        if self._clear_request_count > 0 or admission.local_generation != self._local_generation:
            raise ChatMemoryProjectionClearBoundaryCrossed(
                "Chat memory recovery crossed a local full-clear boundary"
            )
        current_generation = self._normalize_clear_generation(
            await self._read_current_clear_generation()
        )
        if current_generation != admission.clear_generation:
            raise ChatMemoryProjectionClearBoundaryCrossed(
                "Chat memory recovery crossed the durable full-clear generation"
            )

    def ensure_locally_current(
        self,
        admission: ChatMemoryProjectionAdmission,
    ) -> None:
        """Reject stale polling work without repeatedly reading durable storage."""

        if self._clear_request_count > 0 or admission.local_generation != self._local_generation:
            raise ChatMemoryProjectionClearBoundaryCrossed(
                "Chat memory recovery crossed a local full-clear boundary"
            )

    def clear_in_progress(self) -> bool:
        """Return whether a destructive clear is active or waiting for admission."""

        return self._clear_request_count > 0

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Invalidate admitted work, drain it, and block new recovery reads."""

        self._clear_request_count += 1
        self._local_generation += 1
        try:
            async with self._barrier.exclusive():
                yield
        finally:
            self._clear_request_count -= 1

    @staticmethod
    def _normalize_clear_generation(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Clear generation must be a non-negative integer")
        return value


__all__ = [
    "ChatMemoryProjectionAdmission",
    "ChatMemoryProjectionClearBoundaryCrossed",
    "ChatMemoryProjectionClearLifecycle",
]
