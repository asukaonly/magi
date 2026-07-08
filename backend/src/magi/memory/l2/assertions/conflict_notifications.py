"""Scan shadow assertions and materialize 'profile_conflict' notifications.

A shadow assertion is created when an inferred (external-activity) value
conflicts with a user-authoritative row on the same trait key (see
``write.py``).  This module finds active shadows, pairs each with its
surviving authoritative counterpart, and emits a deduped
``profile_conflict`` notification so the user can resolve the discrepancy.

Design decisions for v1:
- **Skip if no authoritative survives**: a conflict notification requires both
  sides (the authoritative the user set + the inferred shadow).  If the
  authoritative was later superseded/archived we skip: there is nothing to
  "confirm against".
- **Dedup key** = ``profile_conflict:{trait_name}:{target_entity_id}`` so one
  conflict per trait slot produces at most one live notification regardless of
  how many times maintenance runs.
- **Kind** is always ``"suggestion"`` to reuse the existing notification feed
  and store schema (``kind`` is the existing string column).
- Notification body is written in Chinese (the default locale) since
  ``locale`` defaults to ``"zh"``; the payload carries raw values for the
  frontend to render localized buttons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from magi.identity.defaults import CANONICAL_LOCAL_USER

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES

logger = get_logger(__name__)
_CANONICAL_SELF_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"

# Statuses that mean an authoritative row is no longer "live".
# Extends RETRIEVAL_EXCLUDED_STATUSES with terminal non-governance statuses that
# also indicate the row is gone from the active pool (superseded, expired,
# contradicted).
_AUTHORITATIVE_EXCLUDED = frozenset(RETRIEVAL_EXCLUDED_STATUSES) | {
    "superseded",
    "expired",
    "contradicted",
}

# Notification kind — reuse the existing suggestion kind so the feed, badge
# count, and store schema all work without schema changes.
_KIND = "suggestion"


@dataclass(frozen=True)
class _ShadowConflictFields:
    trait_name: str
    target_entity_id: str
    inferred_value: str
    shadow_id: str
    entity_type: str


async def _fetch_authoritative(
    db_path: str,
    *,
    entity_id: str,
    entity_type: str,
    trait_name: str,
    target_entity_id: str,
) -> dict[str, Any] | None:
    """Return the most-recent live authoritative row for this trait slot, or None."""
    excluded = list(_AUTHORITATIVE_EXCLUDED)
    placeholders = ", ".join("?" for _ in excluded)
    query = (
        "SELECT * FROM tom_trait_assertions "
        "WHERE entity_id = ? AND entity_type = ? "
        "  AND trait_name = ? AND target_entity_id = ? "
        f" AND status NOT IN ({placeholders}) "
        "ORDER BY updated_at DESC LIMIT 1"
    )
    args: list[Any] = [entity_id, entity_type, trait_name, target_entity_id, *excluded]
    async with sqlite_connection_async(db_path) as db:
        import aiosqlite as _aiosqlite

        db.row_factory = _aiosqlite.Row
        async with db.execute(query, tuple(args)) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


async def materialize_shadow_conflict_notifications(
    store: Any,
    notification_service: Any,
    *,
    user_id: str,
    entity_id: str = _CANONICAL_SELF_ENTITY_ID,
    entity_type: str = "user",
    locale: str = "zh",
) -> dict[str, int]:
    """Find active shadow assertions for *entity_id* and emit deduped
    ``profile_conflict`` notifications for each.

    For each shadow:
    - Reverse-lookup the live authoritative row on the same
      ``(entity_id, entity_type, trait_name, target_entity_id)`` key.
    - If no authoritative row survives (already superseded/archived), skip
      the shadow — a conflict notification needs both sides.
    - Otherwise emit/bump a notification with ``dedupe_key =
      "profile_conflict:{trait_name}:{target_entity_id}"``.

    Args:
        store: An ``L2CognitionStore`` instance (must expose
            ``list_assertions_by_status`` and ``db_path``).
        notification_service: A ``NotificationService`` instance.
        user_id: The canonical self-user ID used as ``user_id`` for
            notification rows.
        entity_id: L2 entity whose shadows we scan.
        entity_type: Entity type string (default: ``"user"``).
        locale: Locale for the notification body (``"zh"`` or ``"en"``).

    Returns:
        Stats dict with keys:
            - ``shadows_seen``: total shadow rows found for *entity_id*
            - ``notifications_emitted``: dedupe-inserts + bumps performed
    """
    shadows: list[dict[str, Any]] = await store.list_assertions_by_status(
        "shadow", entity_id=entity_id
    )
    shadows_seen = len(shadows)
    notifications_emitted = 0

    for shadow in shadows:
        emitted = await _materialize_shadow_conflict_notification(
            store=store,
            notification_service=notification_service,
            shadow=shadow,
            user_id=user_id,
            entity_id=entity_id,
            entity_type=entity_type,
            locale=locale,
        )
        if emitted:
            notifications_emitted += 1

    logger.info(
        "shadow_conflict_notifications: scan complete",
        entity_id=entity_id,
        shadows_seen=shadows_seen,
        notifications_emitted=notifications_emitted,
    )
    return {"shadows_seen": shadows_seen, "notifications_emitted": notifications_emitted}


async def _materialize_shadow_conflict_notification(
    *,
    store: Any,
    notification_service: Any,
    shadow: dict[str, Any],
    user_id: str,
    entity_id: str,
    entity_type: str,
    locale: str,
) -> bool:
    fields = _shadow_conflict_fields(shadow, default_entity_type=entity_type)
    authoritative = await _fetch_authoritative(
        store.db_path,
        entity_id=entity_id,
        entity_type=fields.entity_type,
        trait_name=fields.trait_name,
        target_entity_id=fields.target_entity_id,
    )
    if authoritative is None:
        logger.debug(
            "shadow_conflict_notifications: no surviving authoritative; skipping",
            shadow_id=fields.shadow_id,
            trait_name=fields.trait_name,
        )
        return False

    authoritative_id = str(authoritative.get("assertion_id") or "")
    authoritative_value = str(authoritative.get("trait_value") or "")
    dedupe_key = _shadow_conflict_dedupe_key(fields)
    title, body = _shadow_conflict_notification_text(
        fields=fields,
        authoritative_value=authoritative_value,
        locale=locale,
    )
    payload_json = _shadow_conflict_payload_json(
        fields=fields,
        authoritative_id=authoritative_id,
        authoritative_value=authoritative_value,
        entity_id=entity_id,
    )

    notification_service._materialize_one(user_id, dedupe_key, title, body, payload_json)
    logger.info(
        "shadow_conflict_notifications: notification emitted/bumped",
        shadow_id=fields.shadow_id,
        authoritative_id=authoritative_id,
        trait_name=fields.trait_name,
        dedupe_key=dedupe_key,
    )
    return True


def _shadow_conflict_fields(
    shadow: dict[str, Any],
    *,
    default_entity_type: str,
) -> _ShadowConflictFields:
    return _ShadowConflictFields(
        trait_name=str(shadow.get("trait_name") or ""),
        target_entity_id=str(shadow.get("target_entity_id") or ""),
        inferred_value=str(shadow.get("trait_value") or ""),
        shadow_id=str(shadow.get("assertion_id") or ""),
        entity_type=str(shadow.get("entity_type") or default_entity_type),
    )


def _shadow_conflict_dedupe_key(fields: _ShadowConflictFields) -> str:
    return f"profile_conflict:{fields.trait_name}:{fields.target_entity_id}"


def _shadow_conflict_notification_text(
    *,
    fields: _ShadowConflictFields,
    authoritative_value: str,
    locale: str,
) -> tuple[str, str]:
    if str(locale).startswith("zh"):
        return (
            f"偏好冲突：{fields.trait_name}",
            f"你最近常关注「{fields.inferred_value}」，"
            f"但你说过「{authoritative_value}」—— 要更新偏好吗？",
        )
    return (
        f"Preference conflict: {fields.trait_name}",
        f'You recently showed interest in "{fields.inferred_value}", '
        f'but you previously stated "{authoritative_value}". '
        "Would you like to update your preference?",
    )


def _shadow_conflict_payload_json(
    *,
    fields: _ShadowConflictFields,
    authoritative_id: str,
    authoritative_value: str,
    entity_id: str,
) -> str:
    return json.dumps(
        {
            "conflict_type": "profile_conflict",
            "shadow_id": fields.shadow_id,
            "authoritative_id": authoritative_id,
            "trait_name": fields.trait_name,
            "authoritative_value": authoritative_value,
            "inferred_value": fields.inferred_value,
            "entity_id": entity_id,
        },
        ensure_ascii=False,
    )
