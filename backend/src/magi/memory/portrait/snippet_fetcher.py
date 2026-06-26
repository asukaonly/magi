"""Fetch neutral L2/L3/L4 memory snippets for portrait-like surfaces."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from ..hybrid_retrieval import build_query
from .contracts import MemorySnippetQuery, RawMemorySnippet


logger = logging.getLogger(__name__)


_MAX_SNIPPETS = 15


def build_snippet_fetcher(
    *,
    retrieval_service_provider: Callable[[], Any | None],
) -> Callable[[str, MemorySnippetQuery], Awaitable[list[RawMemorySnippet]]]:
    """Return an async fetcher that converts a topic-like query to snippets."""

    async def fetch(user_id: str, topic_result: MemorySnippetQuery) -> list[RawMemorySnippet]:
        if topic_result.is_empty():
            return []
        service = retrieval_service_provider()
        if service is None:
            return []
        query_text = " ".join(filter(None, [topic_result.topic, *topic_result.entities]))
        try:
            request = build_query(
                query=query_text,
                user_id=user_id,
                session_id=None,
                time_range={},
                query_mode="summary",
                limit=_MAX_SNIPPETS,
            )
            payload = await service.query(request)
        except Exception as exc:
            logger.debug("portrait retrieval failed: %s", exc)
            return []
        return _to_snippets(payload)

    return fetch


def _to_snippets(payload: Any) -> list[RawMemorySnippet]:
    out: list[RawMemorySnippet] = []
    for item in getattr(payload, "l3_reflections", None) or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("content") or "").strip()
        if not statement:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("summary_id") or item.get("id") or f"l3-{len(out)}"),
            kind="reflection",
            layer="L3",
            statement=statement,
            confidence=_safe_float(item.get("confidence")),
        ))
    for item in getattr(payload, "l2_assertions", None) or []:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or item.get("content") or "").strip()
        if not statement:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("assertion_id") or item.get("id") or f"l2a-{len(out)}"),
            kind="assertion",
            layer="L2",
            statement=statement,
            confidence=_safe_float(item.get("confidence")),
        ))
    for item in getattr(payload, "l2_relationships", None) or []:
        if not isinstance(item, dict):
            continue
        subject = str(item.get("subject") or "").strip()
        predicate = str(item.get("predicate") or "").strip()
        obj = str(item.get("object") or "").strip()
        statement = f"{subject} {predicate} {obj}".strip()
        if not statement:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("relationship_id") or item.get("id") or f"l2r-{len(out)}"),
            kind="relationship",
            layer="L2",
            statement=statement,
            confidence=_safe_float(item.get("confidence")),
        ))
    for item in getattr(payload, "l4_procedures", None) or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        if not title:
            continue
        out.append(RawMemorySnippet(
            id=str(item.get("procedure_id") or item.get("id") or f"l4-{len(out)}"),
            kind="procedure",
            layer="L4",
            statement=title,
            confidence=_safe_float(item.get("success_rate")),
        ))
    return out[:_MAX_SNIPPETS]


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
