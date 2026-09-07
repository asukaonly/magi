"""Project conflict notifications from retained assertions without changing their payloads."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import aiosqlite

from magi.core.sqlite import sqlite_connection_async
from magi.i18n import effective_app_language_code

from ..assertion_display import decorate_assertion_display, render_assertion_display
from .state_machine import RETRIEVAL_EXCLUDED_STATUSES


class ConflictAssertionReader(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


def profile_conflict_title(*, language: str | None = None) -> str:
    """Return a title that does not expose an internal trait slot."""
    language = language or effective_app_language_code()
    return "有两条记忆需要核对" if language.startswith("zh") else "Two memory records need review"


def _visible_conflict_assertion(
    assertion: Mapping[str, Any] | None, *, shadow: bool
) -> Mapping[str, Any] | None:
    if not assertion or str(assertion.get("authority_ref") or "").startswith("forget:"):
        return None
    assertion_status = str(assertion.get("status") or "")
    if shadow:
        if assertion_status != "shadow":
            return None
    elif assertion_status in {*RETRIEVAL_EXCLUDED_STATUSES, "superseded", "expired", "contradicted"}:
        return None
    expires_at = assertion.get("expires_at")
    if expires_at is not None and float(expires_at) <= time.time():
        return None
    return assertion


def _retained_conflict_pair(
    authoritative: Mapping[str, Any] | None, shadow: Mapping[str, Any] | None
) -> list[Mapping[str, Any]]:
    previous = _visible_conflict_assertion(authoritative, shadow=False)
    candidate = _visible_conflict_assertion(shadow, shadow=True)
    slot_fields = ("entity_id", "entity_type", "trait_name", "target_entity_id")
    if previous and candidate and any(previous.get(field) != candidate.get(field) for field in slot_fields):
        previous, candidate = None, None
    return [{**(assertion or {}), "natural_summary": ""} for assertion in (previous, candidate)]


async def render_profile_conflict_notification(
    *,
    db_path: str | None,
    shadow: Mapping[str, Any] | None,
    authoritative: Mapping[str, Any] | None,
    language: str | None = None,
) -> tuple[str, str]:
    """Describe the two retained sides without resurfacing copied source text.

    Notifications previously exposed structured values only. Reconstructing from
    those fields preserves that privacy boundary when some source evidence has
    been forgotten while an assertion survives.
    """
    language = language or effective_app_language_code()
    projected = await decorate_assertion_display(
        db_path, _retained_conflict_pair(authoritative, shadow)
    )
    return _render_notification_pair(projected, language=language)


def _render_notification_pair(
    projected: Sequence[Mapping[str, Any]], *, language: str
) -> tuple[str, str]:
    previous, candidate = [render_assertion_display(item, language=language) for item in projected]
    body = (
        f"已有记录：{previous}\n待确认候选：{candidate}"
        if language.startswith("zh")
        else f"Existing record: {previous}\nCandidate awaiting confirmation: {candidate}"
    )
    return profile_conflict_title(language=language), body


async def project_profile_conflict_notifications(
    store: ConflictAssertionReader | None,
    payloads: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str]]:
    """Batch-read retained records and names for a page of existing notifications."""
    assertion_ids = {
        value for payload in payloads for field in ("shadow_id", "authoritative_id")
        if isinstance(value := payload.get(field), str) and value
    }
    assertions: dict[str, Mapping[str, Any]] = {}
    if store is not None and assertion_ids:
        await store.initialize()
        async with sqlite_connection_async(store.db_path) as db:
            db.row_factory = aiosqlite.Row
            unique_ids = sorted(assertion_ids)
            for start in range(0, len(unique_ids), 400):
                batch = unique_ids[start:start + 400]
                placeholders = ", ".join("?" for _ in batch)
                async with db.execute(
                    "SELECT assertion_id, entity_id, entity_type, trait_name, trait_family, "
                    "trait_value, target_entity_id, source_domain, inference_depth, status, "
                    "expires_at, authority_ref, temporal_scope FROM tom_trait_assertions "
                    f"WHERE assertion_id IN ({placeholders}) "
                    "AND COALESCE(authority_ref, '') NOT LIKE 'forget:%'",
                    batch,
                ) as cursor:
                    assertions.update((str(row["assertion_id"]), dict(row)) for row in await cursor.fetchall())
    retained = []
    for payload in payloads:
        pair = []
        for field in ("authoritative_id", "shadow_id"):
            value = payload.get(field)
            pair.append(assertions.get(value) if isinstance(value, str) else None)
        retained.extend(_retained_conflict_pair(pair[0], pair[1]))
    projected = await decorate_assertion_display(store.db_path if store else None, retained)
    language = effective_app_language_code()
    return [
        _render_notification_pair(projected[index:index + 2], language=language)
        for index in range(0, len(projected), 2)
    ]
