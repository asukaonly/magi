"""L3 review-state mutation operations."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async


ALLOWED_REVIEW_STATES = (
    "neutral",
    "pending_confirmation",
    "confirmed",
    "rejected",
    "archived",
)


class _ReviewHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


class L3ReviewOperationsMixin:
    """Write methods for updating review state and user-attached notes."""

    async def set_review_state(
        self,
        *,
        summary_id: str,
        review_state: str,
        user_note: Optional[str] = None,
    ) -> bool:
        """Update a summary's review_state, optionally setting a user note.

        Args:
            summary_id: Target summary primary key.
            review_state: New state; must be in ``ALLOWED_REVIEW_STATES``.
            user_note: When a string, sets or overwrites
                ``insight_metadata.user_note``. When ``None``, the existing
                note is left unchanged. This method cannot clear an existing
                note — pass an empty string only if the caller wants to
                overwrite with empty.

        Returns:
            True if the row existed and was updated, False otherwise.

        Raises:
            ValueError: If ``review_state`` is not in ``ALLOWED_REVIEW_STATES``.
        """
        if review_state not in ALLOWED_REVIEW_STATES:
            raise ValueError(f"invalid review_state: {review_state!r}")
        host = cast(_ReviewHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT insight_metadata FROM summaries WHERE summary_id = ?",
                (summary_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return False
            metadata = _decode_metadata(row["insight_metadata"])
            if user_note is not None:
                metadata["user_note"] = user_note
            await db.execute(
                """
                UPDATE summaries
                SET review_state = ?, insight_metadata = ?, updated_at = ?
                WHERE summary_id = ?
                """,
                (
                    review_state,
                    json.dumps(metadata, ensure_ascii=False),
                    time.time(),
                    summary_id,
                ),
            )
            await db.commit()
        return True

    async def get_summary_by_id(self, summary_id: str) -> Optional[Dict[str, Any]]:
        """Return the summary dict for *summary_id*, or None if not found."""
        host = cast(_ReviewHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM summaries
                WHERE summary_id = ? AND derivation_state = 'current'
                """,
                (summary_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        # _row_to_dict is provided by L3SummaryPersistenceMixin which is always
        # present in L3SummaryStore alongside this mixin.
        return self._row_to_dict(row)  # type: ignore[attr-defined,no-any-return]


def _decode_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return {}
    return {}


__all__ = ["L3ReviewOperationsMixin", "ALLOWED_REVIEW_STATES"]
