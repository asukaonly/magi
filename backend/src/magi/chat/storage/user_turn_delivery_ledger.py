"""Attempt-scoped durable delivery ledger for accepted user turns."""

from __future__ import annotations

from ...core.sqlite import sqlite_connection_async
from ..contracts import (
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_TERMINAL,
    ChatUserTurnDeliveryRecord,
)
from .user_turn_delivery_errors import ChatTurnConflictError
from .user_turn_delivery_rows import (
    fetch_user_turn_delivery_record_row,
    normalize_command_id,
    normalize_delivery_attempt_no,
    row_to_user_turn_delivery_record,
)


class ChatUserTurnDeliveryLedgerPersistenceMixin:
    """Own exact delivery attempts and their compare-and-set transitions."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def mark_user_turn_projection_completed(
        self,
        *,
        turn_id: str,
        updated_at_ms: int,
    ) -> None:
        """Mark the L1 projection stage complete for one persisted user turn."""

        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET projection_completed = 1, updated_at_ms = ?
                    WHERE turn_id = ?
                    """,
                    (int(updated_at_ms), turn_id),
                )
                if int(cursor.rowcount or 0) != 1:
                    raise ChatTurnConflictError(f"Turn '{turn_id}' does not have a delivery state")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def get_user_turn_delivery(
        self,
        *,
        turn_id: str,
    ) -> ChatUserTurnDeliveryRecord | None:
        """Load the current delivery attempt for one accepted user turn."""

        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            row = await fetch_user_turn_delivery_record_row(
                db,
                turn_id=normalized_turn_id,
            )
        return row_to_user_turn_delivery_record(row) if row is not None else None

    async def prepare_user_turn_delivery_attempt(
        self,
        *,
        turn_id: str,
        expected_attempt_no: int,
        updated_at_ms: int,
    ) -> ChatUserTurnDeliveryRecord | None:
        """Atomically invalidate one non-terminal attempt and prepare its successor."""

        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = normalize_delivery_attempt_no(expected_attempt_no)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_attempt_no = delivery_attempt_no + 1,
                        delivery_state = ?,
                        current_command_id = NULL,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND delivery_state != ?
                    """,
                    (
                        CHAT_DELIVERY_STATE_READY,
                        int(updated_at_ms),
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_TERMINAL,
                    ),
                )
                if int(cursor.rowcount or 0) != 1:
                    await db.rollback()
                    return None
                row = await fetch_user_turn_delivery_record_row(
                    db,
                    turn_id=normalized_turn_id,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        if row is None:
            raise ChatTurnConflictError(f"Turn '{normalized_turn_id}' lost its delivery state")
        return row_to_user_turn_delivery_record(row)

    async def mark_user_turn_delivery_queued(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        """Attach the runtime command that durably carries one ready attempt."""

        return await self._transition_user_turn_delivery(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
            expected_state=CHAT_DELIVERY_STATE_READY,
            next_state=CHAT_DELIVERY_STATE_QUEUED,
            attach_command=True,
            updated_at_ms=updated_at_ms,
        )

    async def mark_user_turn_delivery_admitted(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        """Claim one current command before in-memory admission.

        The runtime queue and chat ledger live in separate databases. A queue
        consumer may observe a committed command before ingress records
        ``queued``. The same attempt may therefore move directly from
        ``ready`` to ``admitted`` while attaching that command identity.
        """

        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = normalize_delivery_attempt_no(delivery_attempt_no)
        normalized_command_id = normalize_command_id(command_id)
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE chat_user_turn_delivery
                    SET delivery_state = ?,
                        current_command_id = ?,
                        updated_at_ms = ?
                    WHERE turn_id = ?
                      AND delivery_attempt_no = ?
                      AND (
                          (
                              delivery_state = ?
                              AND current_command_id = ?
                          )
                          OR (
                              delivery_state = ?
                              AND current_command_id IS NULL
                          )
                      )
                    """,
                    (
                        CHAT_DELIVERY_STATE_ADMITTED,
                        normalized_command_id,
                        int(updated_at_ms),
                        normalized_turn_id,
                        normalized_attempt_no,
                        CHAT_DELIVERY_STATE_QUEUED,
                        normalized_command_id,
                        CHAT_DELIVERY_STATE_READY,
                    ),
                )
                changed = int(cursor.rowcount or 0) == 1
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return changed

    async def mark_user_turn_delivery_terminal(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        updated_at_ms: int,
    ) -> bool:
        """Mark the exact admitted attempt terminal after response completion."""

        return await self._transition_user_turn_delivery(
            turn_id=turn_id,
            delivery_attempt_no=delivery_attempt_no,
            command_id=command_id,
            expected_state=CHAT_DELIVERY_STATE_ADMITTED,
            next_state=CHAT_DELIVERY_STATE_TERMINAL,
            attach_command=False,
            updated_at_ms=updated_at_ms,
        )

    async def _transition_user_turn_delivery(
        self,
        *,
        turn_id: str,
        delivery_attempt_no: int,
        command_id: int,
        expected_state: str,
        next_state: str,
        attach_command: bool,
        updated_at_ms: int,
    ) -> bool:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("Turn ID is required")
        normalized_attempt_no = normalize_delivery_attempt_no(delivery_attempt_no)
        normalized_command_id = normalize_command_id(command_id)
        await self.initialize()
        if attach_command:
            statement = """
                UPDATE chat_user_turn_delivery
                SET delivery_state = ?,
                    current_command_id = ?,
                    updated_at_ms = ?
                WHERE turn_id = ?
                  AND delivery_attempt_no = ?
                  AND delivery_state = ?
                  AND current_command_id IS NULL
            """
            params: tuple[object, ...] = (
                next_state,
                normalized_command_id,
                int(updated_at_ms),
                normalized_turn_id,
                normalized_attempt_no,
                expected_state,
            )
        else:
            statement = """
                UPDATE chat_user_turn_delivery
                SET delivery_state = ?,
                    updated_at_ms = ?
                WHERE turn_id = ?
                  AND delivery_attempt_no = ?
                  AND delivery_state = ?
                  AND current_command_id = ?
            """
            params = (
                next_state,
                int(updated_at_ms),
                normalized_turn_id,
                normalized_attempt_no,
                expected_state,
                normalized_command_id,
            )
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(statement, params)
                changed = int(cursor.rowcount or 0) == 1
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return changed


__all__ = ["ChatUserTurnDeliveryLedgerPersistenceMixin"]
