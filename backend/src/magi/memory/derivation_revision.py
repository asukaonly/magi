"""Revision guards for correction-sensitive derived memory artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

import aiosqlite

from .clear_generation import memory_clear_generation_on_connection


class DerivationRevisionChangedError(RuntimeError):
    """Raised when source memory changes while a derived artifact is built."""

    def __init__(self, *, subject_key: str, expected_revision: int, actual_revision: int):
        self.subject_key = subject_key
        self.expected_revision = int(expected_revision)
        self.actual_revision = int(actual_revision)
        super().__init__(
            f"Memory revision changed for {subject_key}: "
            f"expected {expected_revision}, found {actual_revision}"
        )


class MemoryClearGenerationChangedError(RuntimeError):
    """Raised when a destructive clear crosses a derivation build."""

    def __init__(self, *, expected_generation: int, actual_generation: int):
        self.expected_generation = int(expected_generation)
        self.actual_generation = int(actual_generation)
        super().__init__(
            "Memory was cleared while derived content was being built: "
            f"expected generation {expected_generation}, found {actual_generation}"
        )


@dataclass(frozen=True, slots=True)
class DerivationRevision:
    """A source revision captured before derived-content generation starts."""

    subject_key: str
    source_revision: int
    clear_generation: int | None = None

    @classmethod
    async def capture(cls, source: Any, subject_key: str) -> "DerivationRevision":
        """Capture the current revision exposed by an L2-compatible source."""
        if inspect.getattr_static(source, "initialize", None) is not None:
            initializer = getattr(source, "initialize", None)
            if callable(initializer):
                result = initializer()
                if inspect.isawaitable(result):
                    await result
        return cls(
            subject_key=subject_key,
            source_revision=await _current_source_revision(source, subject_key),
            clear_generation=await _current_clear_generation(source),
        )

    async def ensure_current(self, source: Any) -> None:
        """Reject a generated result when its source changed during the build."""
        self.ensure_matches(await _current_source_revision(source, self.subject_key))
        self.ensure_generation_matches(await _current_clear_generation(source))

    async def ensure_current_on_connection(self, db: aiosqlite.Connection) -> None:
        """Validate this revision inside the transaction that will persist it."""
        async with db.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = ?",
            (self.subject_key,),
        ) as cursor:
            row = await cursor.fetchone()
        self.ensure_matches(int(row[0]) if row is not None else 0)
        if self.clear_generation is not None:
            self.ensure_generation_matches(
                await memory_clear_generation_on_connection(db)
            )

    def ensure_matches(self, actual_revision: int) -> None:
        """Raise when *actual_revision* no longer matches the captured value."""
        if int(actual_revision) == self.source_revision:
            return
        raise DerivationRevisionChangedError(
            subject_key=self.subject_key,
            expected_revision=self.source_revision,
            actual_revision=int(actual_revision),
        )

    def ensure_generation_matches(self, actual_generation: int) -> None:
        """Raise when a destructive clear crossed the derivation build."""
        if self.clear_generation is None or int(actual_generation) == self.clear_generation:
            return
        raise MemoryClearGenerationChangedError(
            expected_generation=self.clear_generation,
            actual_generation=int(actual_generation),
        )


async def _current_source_revision(source: Any, subject_key: str) -> int:
    getter = getattr(source, "current_subject_revision", None)
    if getter is None:
        return 0
    return int(await getter(subject_key))


async def _current_clear_generation(source: Any) -> int:
    getter = getattr(source, "current_clear_generation", None)
    if getter is None:
        return 0
    return int(await getter())


__all__ = [
    "DerivationRevision",
    "DerivationRevisionChangedError",
    "MemoryClearGenerationChangedError",
]
