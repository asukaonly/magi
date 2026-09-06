"""L3 review-state mutation operations."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..source_event_governance import active_summary_predicate

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
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT insight_metadata, content, source_event_ids FROM summaries WHERE summary_id = ?",
                (summary_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return False
            metadata = _decode_metadata(row["insight_metadata"])
            if user_note is not None:
                metadata["user_note"] = user_note
            reviewed_at = time.time()
            fingerprint = metadata.get("generation_input_fingerprint")
            history = list(metadata.get("review_history") or [])
            history.append({
                "review_state": review_state,
                "reviewed_at": reviewed_at,
                "generation_input_fingerprint": fingerprint,
                "content": row["content"],
                "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
                "user_note": user_note,
            })
            metadata["review_history"] = history
            if review_state == "rejected" and fingerprint:
                metadata["rejected_input_fingerprints"] = list(dict.fromkeys([
                    *(metadata.get("rejected_input_fingerprints") or []), fingerprint,
                ]))
            elif fingerprint:
                metadata["rejected_input_fingerprints"] = [
                    item for item in metadata.get("rejected_input_fingerprints", [])
                    if item != fingerprint
                ]
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

    async def get_summary_by_id(self, summary_id: str, *, include_rejected: bool = False) -> Optional[Dict[str, Any]]:
        """Return the summary dict for *summary_id*, or None if not found."""
        host = cast(_ReviewHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM summaries
                WHERE summary_id = ? AND {active_summary_predicate(include_rejected=include_rejected)}
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
