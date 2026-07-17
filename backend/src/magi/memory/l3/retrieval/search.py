"""Search result helpers for L3 summary store."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...embedding.embedding_text_builders import build_l3_embedding_text
from ...hybrid_retrieval.fts_utils import tokenize_for_fts
from ...hybrid_retrieval.handlers import rrf_fuse
from ..source_event_governance import active_summary_predicate
from ..storage.serialization import row_to_summary_dict


def rows_to_bm25_pairs(rows: Sequence[Sequence[Any]]) -> list[tuple[str, float]]:
    return [(str(row[0]), float(row[1])) for row in rows]


def ids_from_rows(rows: Sequence[Sequence[Any]]) -> list[str]:
    return [str(row[0]) for row in rows]


def build_keyword_search_query(
    *,
    query: str,
    summary_type: str | None,
    summary_category: str | None,
    limit: int,
) -> tuple[str, tuple[Any, ...]]:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_value = f"%{escaped}%"
    searchable_columns = (
        "content",
        "key_topics",
        "key_entities",
        "sentiment_summary",
        "change_and_pattern",
    )
    predicates = " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in searchable_columns)
    sql = f"""
        SELECT summary_id FROM summaries
        WHERE {active_summary_predicate()} AND ({predicates})
    """
    args: list[Any] = [like_value for _column in searchable_columns]
    if summary_type:
        sql += " AND summary_type = ?"
        args.append(summary_type)
    if summary_category:
        sql += " AND summary_category = ?"
        args.append(summary_category)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(int(limit))
    return sql, tuple(args)


def build_fetch_by_ids_query(
    *,
    summary_ids: Sequence[str],
    summary_type: str | None,
    summary_category: str | None,
) -> tuple[str, tuple[Any, ...]]:
    placeholders = ", ".join("?" for _ in summary_ids)
    sql = f"""
        SELECT * FROM summaries
        WHERE {active_summary_predicate()} AND summary_id IN ({placeholders})
    """
    args: list[Any] = list(summary_ids)
    if summary_type:
        sql += " AND summary_type = ?"
        args.append(summary_type)
    if summary_category:
        sql += " AND summary_category = ?"
        args.append(summary_category)
    return sql, tuple(args)


def ordered_summary_dicts_from_rows(
    *,
    rows: Sequence[Any],
    summary_ids: Sequence[str],
) -> list[dict[str, Any]]:
    summaries_by_id = {str(row["summary_id"]): row_to_summary_dict(row) for row in rows}
    return [
        summaries_by_id[summary_id] for summary_id in summary_ids if summary_id in summaries_by_id
    ]


def fts_backfill_row(row: Any) -> tuple[str, str]:
    summary = row_to_summary_dict(row)
    return str(summary["summary_id"]), tokenize_for_fts(build_l3_embedding_text(summary))


def ranked_vector_summaries(
    *,
    summaries: Sequence[dict[str, Any]],
    summary_ids: Sequence[str],
    matched_chunks: dict[str, list[dict[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    summaries_by_id = {str(summary["summary_id"]): summary for summary in summaries}
    ranked: list[dict[str, Any]] = []
    for summary_id in summary_ids:
        summary = summaries_by_id.get(summary_id)
        if summary is None:
            continue
        summary["matched_chunks"] = matched_chunks.get(summary_id, [])
        if summary["matched_chunks"]:
            summary["distance"] = float(summary["matched_chunks"][0]["distance"])
        ranked.append(summary)
        if len(ranked) >= limit:
            break
    return ranked


def search_path_ids(results_or_errors: Sequence[Any]) -> tuple[list[str], list[str], list[str]]:
    bm25_ids = (
        [summary_id for summary_id, _score in results_or_errors[0]]
        if isinstance(results_or_errors[0], list)
        else []
    )
    semantic_ids = (
        [item["summary_id"] for item in results_or_errors[1]]
        if isinstance(results_or_errors[1], list)
        else []
    )
    keyword_ids = list(results_or_errors[2]) if isinstance(results_or_errors[2], list) else []
    return bm25_ids, semantic_ids, keyword_ids


def fused_summary_ids(
    *,
    bm25_ids: Sequence[str],
    semantic_ids: Sequence[str],
    keyword_ids: Sequence[str],
    fetch_k: int,
) -> list[str]:
    fused = rrf_fuse(
        [list(bm25_ids), list(semantic_ids), list(keyword_ids)],
        [1.0, 1.0, 1.0],
        k=60,
    )
    return [summary_id for summary_id, _score in fused[:fetch_k]]
