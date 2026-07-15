"""Atomic revision fences for correction-sensitive L3 derivations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import aiosqlite

from ..clear_generation import memory_clear_generation_on_connection
from ..derivation_revision import DerivationRevision


@dataclass(frozen=True, slots=True)
class L3DerivationFence:
    """Source revisions and clear generation captured from one database view."""

    revisions: dict[str, int]
    clear_generation: int

    @classmethod
    async def capture_on_connection(
        cls,
        db: aiosqlite.Connection,
        subject_keys: Iterable[str],
    ) -> "L3DerivationFence":
        """Capture all requested revisions and the clear generation together."""
        subjects = list(
            dict.fromkeys(
                str(subject_key).strip()
                for subject_key in subject_keys
                if str(subject_key).strip()
            )
        )
        revisions = {subject_key: 0 for subject_key in subjects}
        if subjects:
            placeholders = ", ".join("?" for _ in subjects)
            async with db.execute(
                f"""
                SELECT subject_key, revision
                FROM memory_subject_revisions
                WHERE subject_key IN ({placeholders})
                """,
                tuple(subjects),
            ) as cursor:
                rows = await cursor.fetchall()
            revisions.update({str(row[0]): int(row[1]) for row in rows})
        return cls(
            revisions=revisions,
            clear_generation=await memory_clear_generation_on_connection(db),
        )

    async def ensure_current_on_connection(self, db: aiosqlite.Connection) -> None:
        """Reject a write if any source revision or clear generation changed."""
        for subject_key, source_revision in self.revisions.items():
            await DerivationRevision(
                subject_key=subject_key,
                source_revision=source_revision,
                clear_generation=self.clear_generation,
            ).ensure_current_on_connection(db)
        if not self.revisions:
            DerivationRevision(
                subject_key="",
                source_revision=0,
                clear_generation=self.clear_generation,
            ).ensure_generation_matches(
                await memory_clear_generation_on_connection(db)
            )

    @property
    def source_revision(self) -> int:
        """Return the highest captured subject revision for summary metadata."""
        return max(self.revisions.values(), default=0)


__all__ = ["L3DerivationFence"]
