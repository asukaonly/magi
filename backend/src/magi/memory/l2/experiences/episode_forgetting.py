"""Transactional dependency cleanup for user-forgotten episodes."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import aiosqlite

from .source_event_forgetting import delete_experience_drafts_for_source_references


async def invalidate_episode_dependencies(
    db: aiosqlite.Connection,
    *,
    episode_id: str,
    now: float,
) -> dict[str, int]:
    """Invalidate every user-visible derivation that depends on one episode."""
    return await invalidate_episode_dependencies_many(
        db,
        episode_ids=(episode_id,),
        now=now,
    )


async def invalidate_episode_dependencies_many(
    db: aiosqlite.Connection,
    *,
    episode_ids: Iterable[str],
    now: float,
) -> dict[str, int]:
    """Invalidate a broad episode set while counting shared derivations once."""
    normalized_episode_ids = tuple(
        dict.fromkeys(str(item).strip() for item in episode_ids if str(item).strip())
    )
    if not normalized_episode_ids:
        return {
            "experiences": 0,
            "experience_seeds": 0,
            "experience_drafts": 0,
            "summaries": 0,
        }
    affected_experiences: set[str] = set()
    affected_summaries: set[str] = set()
    affected_seeds: set[str] = set()

    while True:
        before = (
            len(affected_experiences),
            len(affected_summaries),
            len(affected_seeds),
        )
        for episode_id in normalized_episode_ids:
            affected_experiences.update(
                await _experience_ids_for_episode_and_seeds(
                    db,
                    episode_id=episode_id,
                    seed_ids=affected_seeds,
                )
            )
            affected_summaries.update(
                await _summary_ids_for_episode_and_experiences(
                    db,
                    episode_id=episode_id,
                    experience_ids=affected_experiences,
                )
            )
            affected_seeds.update(
                await _seed_ids_for_episode_and_summaries(
                    db,
                    episode_id=episode_id,
                    summary_ids=affected_summaries,
                )
            )
        after = (
            len(affected_experiences),
            len(affected_summaries),
            len(affected_seeds),
        )
        if after == before:
            break

    deleted_drafts = await delete_experience_drafts_for_source_references(
        db,
        episode_ids=list(normalized_episode_ids),
    )
    await _invalidate_summaries(db, summary_ids=affected_summaries, now=now)
    for episode_id in normalized_episode_ids:
        await _stale_seeds(
            db,
            seed_ids=affected_seeds,
            episode_id=episode_id,
            summary_ids=affected_summaries,
            now=now,
        )
        await _invalidate_experiences(
            db,
            experience_ids=affected_experiences,
            episode_id=episode_id,
            now=now,
        )
    episode_json = _json_ids(normalized_episode_ids)
    await db.execute(
        """
        UPDATE episodes
        SET status = 'invalidated', embedding_status = 'pending',
            embedding_profile_id = NULL, last_embedded_at = NULL,
            last_recomputed_at = ?, updated_at = ?
        WHERE episode_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (now, now, episode_json),
    )
    await db.execute(
        """
        DELETE FROM episodes_fts
        WHERE episode_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (episode_json,),
    )
    return {
        "experiences": len(affected_experiences),
        "experience_seeds": len(affected_seeds),
        "experience_drafts": deleted_drafts,
        "summaries": len(affected_summaries),
    }


async def _experience_ids_for_episode_and_seeds(
    db: aiosqlite.Connection,
    *,
    episode_id: str,
    seed_ids: set[str],
) -> set[str]:
    seed_json = _json_ids(seed_ids)
    return await _select_ids(
        db,
        """
        SELECT DISTINCT experience_id
        FROM experience_members
        WHERE member_type = 'episode' AND member_id = ?
        UNION
        SELECT DISTINCT experience_id
        FROM experience_chapters AS chapter
        WHERE EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(chapter.episode_ids_json)
                    THEN chapter.episode_ids_json
                ELSE '[]'
            END) AS ref
            WHERE CAST(ref.value AS TEXT) = ?
        )
        UNION
        SELECT experience_id
        FROM experiences
        WHERE source_seed_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        UNION
        SELECT promoted_experience_id
        FROM experience_seeds
        WHERE seed_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        ) AND promoted_experience_id IS NOT NULL
        """,
        (episode_id, episode_id, seed_json, seed_json),
    )


async def _summary_ids_for_episode_and_experiences(
    db: aiosqlite.Connection,
    *,
    episode_id: str,
    experience_ids: set[str],
) -> set[str]:
    experience_json = _json_ids(experience_ids)
    return await _select_ids(
        db,
        """
        SELECT summary_id
        FROM summaries
        WHERE json_extract(
            CASE WHEN json_valid(insight_metadata) THEN insight_metadata ELSE '{}' END,
            '$.source_episode_id'
        ) = ?
        OR EXISTS (
            SELECT 1
            FROM json_each(CASE
                WHEN json_valid(json_extract(
                    CASE WHEN json_valid(insight_metadata)
                        THEN insight_metadata ELSE '{}' END,
                    '$.source_episode_ids'
                ))
                    THEN json_extract(insight_metadata, '$.source_episode_ids')
                ELSE '[]'
            END) AS ref
            WHERE CAST(ref.value AS TEXT) = ?
        )
        OR json_extract(
            CASE WHEN json_valid(insight_metadata) THEN insight_metadata ELSE '{}' END,
            '$.source_experience_id'
        ) IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (episode_id, episode_id, experience_json),
    )


async def _seed_ids_for_episode_and_summaries(
    db: aiosqlite.Connection,
    *,
    episode_id: str,
    summary_ids: set[str],
) -> set[str]:
    summary_json = _json_ids(summary_ids)
    seed_ids = await _select_ids(
        db,
        """
        SELECT DISTINCT seed_id
        FROM experience_seed_evidence
        WHERE (ref_type = 'episode' AND ref_id = ?)
           OR (ref_type = 'summary' AND ref_id IN (
               SELECT CAST(value AS TEXT) FROM json_each(?)
           ))
        UNION
        SELECT DISTINCT seed_id
        FROM experience_seeds
        WHERE (source_ref_type = 'episode' AND source_ref_id = ?)
           OR (source_ref_type = 'summary' AND source_ref_id IN (
               SELECT CAST(value AS TEXT) FROM json_each(?)
           ))
        """,
        (episode_id, summary_json, episode_id, summary_json),
    )
    seed_ids.update(await _episode_group_seed_ids(db, episode_id=episode_id))
    return seed_ids


async def _episode_group_seed_ids(
    db: aiosqlite.Connection,
    *,
    episode_id: str,
) -> set[str]:
    """Match legacy comma-separated groups after trimming each member."""
    async with db.execute("""
        SELECT seed_id, source_ref_id
        FROM experience_seeds
        WHERE source_ref_type = 'episode_group'
        """) as cursor:
        rows = await cursor.fetchall()
    return {
        str(row[0])
        for row in rows
        if episode_id in {item.strip() for item in str(row[1] or "").split(",") if item.strip()}
    }


async def _invalidate_summaries(
    db: aiosqlite.Connection,
    *,
    summary_ids: set[str],
    now: float,
) -> None:
    if not summary_ids:
        return
    summary_json = _json_ids(summary_ids)
    await db.execute(
        """
        UPDATE summaries
        SET derivation_state = 'retired', updated_at = ?
        WHERE summary_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (now, summary_json),
    )
    await db.execute(
        """
        DELETE FROM l3_summaries_fts
        WHERE summary_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (summary_json,),
    )


async def _stale_seeds(
    db: aiosqlite.Connection,
    *,
    seed_ids: set[str],
    episode_id: str,
    summary_ids: set[str],
    now: float,
) -> None:
    if not seed_ids:
        return
    seed_json = _json_ids(seed_ids)
    summary_json = _json_ids(summary_ids)
    source_ref_seed_ids = await _select_ids(
        db,
        """
        SELECT seed_id
        FROM experience_seeds
        WHERE seed_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND (
              (source_ref_type = 'episode' AND source_ref_id = ?)
              OR (source_ref_type = 'summary' AND source_ref_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              ))
          )
        """,
        (seed_json, episode_id, summary_json),
    )
    source_ref_seed_ids.update(
        seed_ids.intersection(await _episode_group_seed_ids(db, episode_id=episode_id))
    )
    source_ref_seed_json = _json_ids(source_ref_seed_ids)
    await db.execute(
        """
        DELETE FROM experience_seed_evidence
        WHERE seed_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND (
              (ref_type = 'episode' AND ref_id = ?)
              OR (ref_type = 'summary' AND ref_id IN (
                  SELECT CAST(value AS TEXT) FROM json_each(?)
              ))
          )
        """,
        (seed_json, episode_id, summary_json),
    )
    await db.execute(
        """
        UPDATE experience_seeds
        SET status = 'stale',
            title = NULL,
            description = NULL,
            source_ref_type = CASE
                WHEN seed_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                THEN NULL ELSE source_ref_type END,
            source_ref_id = CASE
                WHEN seed_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                THEN NULL ELSE source_ref_id END,
            promoted_experience_id = NULL,
            updated_at = ?, last_evaluated_at = ?
        WHERE seed_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """,
        (
            source_ref_seed_json,
            source_ref_seed_json,
            now,
            now,
            seed_json,
        ),
    )


async def _invalidate_experiences(
    db: aiosqlite.Connection,
    *,
    experience_ids: set[str],
    episode_id: str,
    now: float,
) -> None:
    if not experience_ids:
        return
    experience_json = _json_ids(experience_ids)
    await db.execute(
        """
        DELETE FROM experience_members
        WHERE member_type = 'episode' AND member_id = ?
          AND experience_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (episode_id, experience_json),
    )
    await _remove_episode_from_chapters(
        db,
        experience_ids=experience_ids,
        episode_id=episode_id,
        now=now,
    )
    for experience_id in experience_ids:
        source_episode_count, source_event_count = await _experience_source_counts(
            db,
            experience_id=experience_id,
        )
        await db.execute(
            """
            UPDATE experiences
            SET status = 'invalidated', source_episode_count = ?,
                source_event_count = ?, last_recomputed_at = ?, updated_at = ?
            WHERE experience_id = ?
            """,
            (source_episode_count, source_event_count, now, now, experience_id),
        )


async def _remove_episode_from_chapters(
    db: aiosqlite.Connection,
    *,
    experience_ids: set[str],
    episode_id: str,
    now: float,
) -> None:
    if not experience_ids:
        return
    experience_json = _json_ids(experience_ids)
    async with db.execute(
        """
        SELECT experience_id, chapter_id, episode_ids_json
        FROM experience_chapters
        WHERE experience_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (experience_json,),
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        episode_ids = _safe_json_id_list(row[2])
        if episode_id not in episode_ids:
            continue
        await db.execute(
            """
            UPDATE experience_chapters
            SET episode_ids_json = ?, updated_at = ?
            WHERE experience_id = ? AND chapter_id = ?
            """,
            (
                json.dumps(
                    [candidate for candidate in episode_ids if candidate != episode_id],
                    ensure_ascii=False,
                ),
                now,
                str(row[0]),
                str(row[1]),
            ),
        )


async def _experience_source_counts(
    db: aiosqlite.Connection,
    *,
    experience_id: str,
) -> tuple[int, int]:
    async with db.execute(
        """
        SELECT COUNT(DISTINCT member_id)
        FROM experience_members
        WHERE experience_id = ? AND member_type = 'episode' AND role != 'excluded'
        """,
        (experience_id,),
    ) as cursor:
        episode_row = await cursor.fetchone()
    async with db.execute(
        """
        SELECT COUNT(DISTINCT event_id) FROM (
            SELECT episode_events.event_id
            FROM experience_members
            JOIN episode_events ON episode_events.episode_id = experience_members.member_id
            WHERE experience_members.experience_id = ?
              AND experience_members.member_type = 'episode'
              AND experience_members.role != 'excluded'
            UNION
            SELECT member_id AS event_id FROM experience_members
            WHERE experience_id = ? AND member_type = 'event' AND role != 'excluded'
        )
        """,
        (experience_id, experience_id),
    ) as cursor:
        event_row = await cursor.fetchone()
    return (
        int(episode_row[0]) if episode_row else 0,
        int(event_row[0]) if event_row else 0,
    )


async def _select_ids(
    db: aiosqlite.Connection,
    query: str,
    args: tuple[Any, ...],
) -> set[str]:
    async with db.execute(query, args) as cursor:
        return {
            str(row[0]).strip()
            for row in await cursor.fetchall()
            if row[0] is not None and str(row[0]).strip()
        }


def _json_ids(values: Iterable[str]) -> str:
    return json.dumps(
        list(dict.fromkeys(str(value).strip() for value in values if str(value).strip())),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _safe_json_id_list(value: Any) -> list[str]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return list(dict.fromkeys(str(item) for item in decoded if str(item).strip()))


__all__ = ["invalidate_episode_dependencies", "invalidate_episode_dependencies_many"]
