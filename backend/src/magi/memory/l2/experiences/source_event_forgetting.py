"""Fail-closed cleanup for experience drafts derived from deleted events."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import aiosqlite

from ...source_event_governance import normalize_source_event_ids


async def delete_experience_drafts_for_source_events(
    db: aiosqlite.Connection,
    *,
    event_ids: Iterable[str],
) -> int:
    """Delete drafts that copy any supplied event or one of its episodes.

    This helper accepts an existing transaction so the L2 source-forget path can
    run it before removing ``episode_events`` memberships.
    """
    return await delete_experience_drafts_for_source_references(
        db,
        event_ids=event_ids,
    )


async def delete_experience_drafts_for_source_references(
    db: aiosqlite.Connection,
    *,
    event_ids: Iterable[str] = (),
    episode_ids: Iterable[str] = (),
) -> int:
    """Delete drafts that copy any supplied event or episode reference."""
    normalized = normalize_source_event_ids(event_ids)
    explicit_episode_ids = {
        str(episode_id).strip() for episode_id in episode_ids if str(episode_id).strip()
    }
    if not normalized and not explicit_episode_ids:
        return 0

    affected_episode_ids = set(explicit_episode_ids)
    if normalized:
        event_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        async with db.execute(
            """
            SELECT DISTINCT episode_id
            FROM episode_events
            WHERE event_id IN (
                SELECT CAST(value AS TEXT) FROM json_each(?)
            )
            """,
            (event_json,),
        ) as cursor:
            affected_episode_ids.update(
                str(row[0]).strip()
                for row in await cursor.fetchall()
                if row[0] is not None and str(row[0]).strip()
            )

    async with db.execute("""
        SELECT draft_id, chapters_json, possible_evidence_json,
               excluded_evidence_json
        FROM experience_drafts
        """) as cursor:
        rows = await cursor.fetchall()

    target_event_ids = set(normalized)
    affected_draft_ids: list[str] = []
    for row in rows:
        draft_id = str(row[0])
        referenced_event_ids: set[str] = set()
        referenced_episode_ids: set[str] = set()
        valid = True
        for raw_value in row[1:]:
            decoded, field_valid = _decode_reference_field(raw_value)
            valid = valid and field_valid
            if field_valid:
                _collect_references(
                    decoded,
                    event_ids=referenced_event_ids,
                    episode_ids=referenced_episode_ids,
                )
        if (
            not valid
            or referenced_event_ids.intersection(target_event_ids)
            or referenced_episode_ids.intersection(affected_episode_ids)
        ):
            affected_draft_ids.append(draft_id)

    if not affected_draft_ids:
        return 0
    await db.executemany(
        "DELETE FROM experience_drafts WHERE draft_id = ?",
        [(draft_id,) for draft_id in affected_draft_ids],
    )
    return len(affected_draft_ids)


def collect_experience_draft_source_references(
    *,
    chapters: Any,
    possible_evidence: Any,
    excluded_evidence: Any,
) -> tuple[set[str], set[str]]:
    """Return every episode and event reference copied into a draft."""
    event_ids: set[str] = set()
    episode_ids: set[str] = set()
    for value in (chapters, possible_evidence, excluded_evidence):
        if not isinstance(value, list):
            raise ValueError("Experience draft evidence fields must be lists")
        _collect_references(
            value,
            event_ids=event_ids,
            episode_ids=episode_ids,
        )
    return episode_ids, event_ids


def _decode_reference_field(value: Any) -> tuple[Any, bool]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return None, False
    if not isinstance(decoded, list):
        return None, False
    return decoded, True


def _collect_references(
    value: Any,
    *,
    event_ids: set[str],
    episode_ids: set[str],
) -> None:
    if isinstance(value, Mapping):
        ref_type = str(value.get("ref_type") or "").strip()
        ref_id = _clean_id(value.get("ref_id"))
        if ref_type == "event" and ref_id:
            event_ids.add(ref_id)
        elif ref_type == "episode" and ref_id:
            episode_ids.add(ref_id)

        for key, nested in value.items():
            if key in {"event_id", "event_ids"}:
                event_ids.update(_reference_ids(nested))
            elif key in {"episode_id", "episode_ids"}:
                episode_ids.update(_reference_ids(nested))
            if isinstance(nested, (Mapping, list, tuple)):
                _collect_references(
                    nested,
                    event_ids=event_ids,
                    episode_ids=episode_ids,
                )
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _collect_references(
                item,
                event_ids=event_ids,
                episode_ids=episode_ids,
            )


def _reference_ids(value: Any) -> set[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return {cleaned for item in values if (cleaned := _clean_id(item))}


def _clean_id(value: Any) -> str:
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return ""
    return str(value).strip()


__all__ = [
    "collect_experience_draft_source_references",
    "delete_experience_drafts_for_source_events",
    "delete_experience_drafts_for_source_references",
]
