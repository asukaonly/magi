"""Search result helpers for L4 procedural memory."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...hybrid_retrieval.fts_utils import tokenize_for_fts
from ..storage.serialization import row_to_skill_dict


def plain_skill_like_pattern(query: str) -> str:
    return f"%{query}%"


def escaped_skill_like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def rows_to_bm25_pairs(rows: Sequence[Sequence[Any]]) -> list[tuple[str, float]]:
    return [(str(row[0]), float(row[1])) for row in rows]


def ids_from_rows(rows: Sequence[Sequence[Any]]) -> list[str]:
    return [str(row[0]) for row in rows]


def ordered_skill_dicts_from_rows(
    *,
    rows: Sequence[Mapping[str, Any]],
    skill_ids: Sequence[str],
) -> list[dict[str, Any]]:
    by_id = {str(row["skill_id"]): row_to_skill_dict(row) for row in rows}
    return [by_id[skill_id] for skill_id in skill_ids if skill_id in by_id]


def fts_backfill_row(row: Sequence[Any]) -> tuple[str, str]:
    skill_id = str(row[0])
    text = f"{row[1]} {row[2]} {row[3] or ''}"
    return skill_id, tokenize_for_fts(text)


def ranked_semantic_skills(
    *,
    rows: Sequence[Mapping[str, Any]],
    skill_ids: Sequence[str],
    matched_chunks: Mapping[str, list[dict[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    skills_by_id = {str(row["skill_id"]): row_to_skill_dict(row) for row in rows}
    ranked: list[dict[str, Any]] = []
    for skill_id in skill_ids:
        skill = skills_by_id.get(skill_id)
        if skill is None:
            continue
        skill["matched_chunks"] = matched_chunks.get(skill_id, [])
        if skill["matched_chunks"]:
            skill["distance"] = float(skill["matched_chunks"][0]["distance"])
        ranked.append(skill)
        if len(ranked) >= limit:
            break
    return ranked
