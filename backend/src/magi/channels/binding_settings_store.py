"""ChannelBindingSettingsStore — Phase H+2 per-binding settings.

Backs the "外部渠道免审批" (external-channel auto-approve) toggle the
user can flip from desktop Settings → Channels. Keyed by
``(channel_type, external_user_id)`` — one row per WeChat OpenID /
Telegram user_id — so the same person on different channels can
have different policies (a careful Telegram setup that gates every
tool, plus a trusted personal WeChat that auto-approves).

Default state is "no row" → ``auto_approve=False``. Bootstrap and
the API layer both treat absence as "not auto-approved" without
materializing rows for every binding the user has ever used.

Schema is part of the channels alembic baseline
(``backend/src/magi/db/migrations/channels/versions/0001_initial.py``).
Pre-launch convention: no separate migration script for this
table — extended in-place on 0001_initial.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from ..core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ChannelBindingSettings:
    """The settings row (or virtual-default if no row exists yet)."""

    channel_type: str
    external_user_id: str
    auto_approve: bool
    updated_at_ms: int


class ChannelBindingSettingsStore:
    """Per-binding settings (auto_approve flag) read/write.

    Reads MUST be defensive: a brand-new binding never has a row yet,
    so ``get`` returns a virtual default rather than None. This
    matches the API contract ("the toggle is always meaningful for
    every binding the user has connected"); callers don't need to
    distinguish "no row" from "row exists with auto_approve=False".
    """

    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    async def get(
        self, *, channel_type: str, external_user_id: str
    ) -> ChannelBindingSettings:
        """Return current settings for the binding, or a virtual
        default (auto_approve=False) when no row exists yet."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT auto_approve, updated_at_ms
                  FROM channel_binding_settings
                 WHERE channel_type = ? AND external_user_id = ?
                """,
                (channel_type, external_user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return ChannelBindingSettings(
                channel_type=channel_type,
                external_user_id=external_user_id,
                auto_approve=False,
                updated_at_ms=0,
            )
        return ChannelBindingSettings(
            channel_type=channel_type,
            external_user_id=external_user_id,
            auto_approve=bool(row[0]),
            updated_at_ms=int(row[1]),
        )

    async def set_auto_approve(
        self,
        *,
        channel_type: str,
        external_user_id: str,
        auto_approve: bool,
    ) -> ChannelBindingSettings:
        """Upsert the auto_approve flag for this binding.

        Idempotent — calling with the same value twice is a no-op
        from the user's perspective (we still bump updated_at_ms
        so audit logs can trace the user's intent)."""
        if not channel_type or not channel_type.strip():
            raise ValueError("channel_type must be non-empty")
        if not external_user_id or not external_user_id.strip():
            raise ValueError("external_user_id must be non-empty")
        now_ms = int(time.time() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO channel_binding_settings(
                    channel_type, external_user_id, auto_approve, updated_at_ms
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(channel_type, external_user_id) DO UPDATE SET
                    auto_approve = excluded.auto_approve,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (channel_type, external_user_id, 1 if auto_approve else 0, now_ms),
            )
            await db.commit()
        return ChannelBindingSettings(
            channel_type=channel_type,
            external_user_id=external_user_id,
            auto_approve=auto_approve,
            updated_at_ms=now_ms,
        )

    async def list_all(self) -> list[ChannelBindingSettings]:
        """Snapshot of every row (the UI uses this to render the
        full list of bindings the user has ever toggled)."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT channel_type, external_user_id,
                       auto_approve, updated_at_ms
                  FROM channel_binding_settings
                 ORDER BY updated_at_ms DESC
                """
            )
            rows = await cursor.fetchall()
        return [
            ChannelBindingSettings(
                channel_type=str(r[0]),
                external_user_id=str(r[1]),
                auto_approve=bool(r[2]),
                updated_at_ms=int(r[3]),
            )
            for r in rows
        ]


__all__ = ["ChannelBindingSettings", "ChannelBindingSettingsStore"]
