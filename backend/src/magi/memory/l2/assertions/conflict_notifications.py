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
- Notification text uses the shared fact renderer; the payload retains its
  structured resolution values and stable assertion IDs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from magi.identity.defaults import CANONICAL_LOCAL_USER
from magi.notifications.service import NotificationService

from ....core.logger import get_logger
from ..retrieval.shadow_conflicts import ShadowConflictReader
from .conflict_notification_display import render_profile_conflict_notifications

logger = get_logger(__name__)
_CANONICAL_SELF_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


@dataclass(frozen=True)
class _ShadowConflictFields:
    trait_name: str
    target_entity_id: str
    inferred_value: str
    shadow_id: str


async def materialize_shadow_conflict_notifications(
    store: ShadowConflictReader,
    notification_service: NotificationService,
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
        store: The L2 domain's conflict query boundary.
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
    scan = await store.list_shadow_conflicts(entity_id=entity_id, entity_type=entity_type)
    texts = await render_profile_conflict_notifications(
        db_path=store.db_path,
        pairs=scan.pairs,
        language=locale,
    )
    notifications_emitted = 0
    for pair, (title, body) in zip(scan.pairs, texts):
        assert pair.shadow is not None and pair.authoritative is not None
        fields = _shadow_conflict_fields(pair.shadow)
        authoritative_id = str(pair.authoritative["assertion_id"])
        authoritative_value = str(pair.authoritative["trait_value"])
        dedupe_key = _shadow_conflict_dedupe_key(fields)
        payload_json = _shadow_conflict_payload_json(
            fields=fields,
            authoritative_id=authoritative_id,
            authoritative_value=authoritative_value,
            entity_id=entity_id,
        )
        notification_service._materialize_one(user_id, dedupe_key, title, body, payload_json)
        notifications_emitted += 1
        logger.info(
            "shadow_conflict_notifications: notification emitted/bumped",
            shadow_id=fields.shadow_id,
            authoritative_id=authoritative_id,
            trait_name=fields.trait_name,
            dedupe_key=dedupe_key,
        )

    logger.info(
        "shadow_conflict_notifications: scan complete",
        entity_id=entity_id,
        shadows_seen=scan.shadows_seen,
        notifications_emitted=notifications_emitted,
    )
    return {"shadows_seen": scan.shadows_seen, "notifications_emitted": notifications_emitted}


def _shadow_conflict_fields(
    shadow: dict[str, Any],
) -> _ShadowConflictFields:
    return _ShadowConflictFields(
        trait_name=str(shadow.get("trait_name") or ""),
        target_entity_id=str(shadow.get("target_entity_id") or ""),
        inferred_value=str(shadow.get("trait_value") or ""),
        shadow_id=str(shadow.get("assertion_id") or ""),
    )


def _shadow_conflict_dedupe_key(fields: _ShadowConflictFields) -> str:
    return f"profile_conflict:{fields.trait_name}:{fields.target_entity_id}"


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
