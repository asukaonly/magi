"""Persistence helpers for accepted chat context-usage snapshots."""

from __future__ import annotations

from typing import Any

import aiosqlite

from ..contracts import ChatContextUsageSnapshot


def normalize_context_usage_snapshot(
    *,
    turn_id: str,
    session_id: str,
    user_id: str,
    context_usage: dict[str, Any] | None,
    updated_at_ms: int,
) -> ChatContextUsageSnapshot | None:
    """Validate a runtime usage candidate for durable chat ownership."""

    if not isinstance(context_usage, dict):
        return None
    used_tokens = _positive_int(context_usage.get("used_tokens"))
    context_window = _positive_int(
        context_usage.get("context_window") or context_usage.get("window_size")
    )
    input_capacity = _positive_int(context_usage.get("input_capacity"))
    compaction_threshold = _positive_int(
        context_usage.get("compaction_threshold") or context_usage.get("threshold")
    )
    measurement = str(context_usage.get("measurement") or "").strip().lower()
    if measurement not in {"actual", "estimated"}:
        return None
    if (
        used_tokens is None
        or context_window is None
        or input_capacity is None
        or compaction_threshold is None
    ):
        return None
    return ChatContextUsageSnapshot(
        turn_id=turn_id,
        session_id=session_id,
        user_id=user_id,
        used_tokens=used_tokens,
        context_window=context_window,
        input_capacity=input_capacity,
        compaction_threshold=compaction_threshold,
        measurement=measurement,
        model_provider=_optional_text(context_usage.get("model_provider")),
        model_id=_optional_text(context_usage.get("model_id")),
        updated_at_ms=int(updated_at_ms),
    )


async def insert_context_usage_snapshot(
    db: aiosqlite.Connection,
    snapshot: ChatContextUsageSnapshot,
) -> None:
    """Insert the immutable usage row for an accepted turn."""

    await db.execute(
        """
        INSERT INTO chat_context_usage_snapshots(
            turn_id, session_id, user_id, used_tokens, context_window,
            input_capacity, compaction_threshold, measurement,
            model_provider, model_id, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.turn_id,
            snapshot.session_id,
            snapshot.user_id,
            snapshot.used_tokens,
            snapshot.context_window,
            snapshot.input_capacity,
            snapshot.compaction_threshold,
            snapshot.measurement,
            snapshot.model_provider,
            snapshot.model_id,
            snapshot.updated_at_ms,
        ),
    )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


__all__ = [
    "insert_context_usage_snapshot",
    "normalize_context_usage_snapshot",
]
