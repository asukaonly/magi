"""Compact, governed memory read models shared by native product clients."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import HTTPException, Query
from pydantic import Field

from ....core.client_models import ClientModel
from ....memory.evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from . import dependencies
from .helpers import canonical_self_id
from .portrait_self_routes import _get_self_portrait
from .router import memory_router
from .schemas import RetrievalRequest
from .search_routes import search_memory
from .stories_routes import _list_story_feed


class MemoryLibraryItem(ClientModel):
    id: str
    kind: Literal["fact", "event", "story", "experience"]
    text: str
    title: str = ""
    source: str = ""
    timestamp: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    assertion_id: str | None = None
    correction_value: str | None = None
    correction_options: list[str] | None = None
    updated_at: float | None = None
    needs_review: bool = False
    can_delete: bool = False


class MemoryLibraryPage(ClientModel):
    items: list[MemoryLibraryItem]
    total: int
    limit: int
    offset: int
    stale: bool = False


def _event(row: dict) -> MemoryLibraryItem:
    identity = str(row["event_id"])
    source = str(row.get("source") or "")
    return MemoryLibraryItem(
        id=identity, kind="event", text=str(row.get("content") or ""),
        source=source, timestamp=row.get("timestamp"), evidence_ids=[identity],
        can_delete=source != "manual_entry",
    )


def _fact(row: dict, *, review: bool = False) -> MemoryLibraryItem:
    return MemoryLibraryItem(
        id=str(row.get("id") or row["assertion_id"]), kind="fact",
        text=str(row.get("text") or row.get("display_text") or ""),
        source=str(row.get("source") or ""), timestamp=row.get("updated_at"),
        evidence_ids=[str(value) for value in row.get("basis_refs", [])],
        assertion_id=row.get("assertion_id"), correction_value=row.get("correction_value"),
        correction_options=row.get("correction_value_options"),
        updated_at=row.get("updated_at"), needs_review=review,
    )


@memory_router.get("/library", response_model=MemoryLibraryPage)
async def memory_library(
    view: Literal["about", "events", "stories"] = "about",
    query: str = Query(default="", max_length=500),
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MemoryLibraryPage:
    """Reuse governed domain reads; never export database or embedding payloads."""
    memory = dependencies._resolve_unified_memory()
    if memory is None:
        raise HTTPException(503, "Memory is unavailable")
    if query.strip():
        result = await search_memory(RetrievalRequest(query=query.strip(), limit=100))
        items = [_event(row) for row in result.get("l1_events", [])]
        items.extend(_fact(row) for row in result.get("l2_assertions", []) if row.get("display_text"))
        for row in result.get("l2_experiences", []):
            if row.get("experience_id"):
                items.append(MemoryLibraryItem(id=row["experience_id"], kind="experience",
                    title=str(row.get("title") or ""), text=str(row.get("summary") or row.get("content") or "")))
        unique = {(item.kind, item.id): item for item in items}
        items = list(unique.values())
        return MemoryLibraryPage(items=items[offset:offset + limit], total=len(items), limit=limit, offset=offset)
    if view == "about":
        portrait = await _get_self_portrait(canonical_self_id(memory))
        content = portrait["self_view"]
        items = [_fact(row) for group in content["world"]["groups"] for row in group["items"]]
        items.extend(_fact(row) for row in content["recent"]["items"])
        items.extend(_fact(row, review=True) for row in content["review"]["items"])
        return MemoryLibraryPage(items=items[offset:offset + limit], total=len(items), limit=limit,
                                 offset=offset, stale=portrait["is_stale"])
    if view == "stories":
        page = await _list_story_feed(limit=limit, offset=offset, surface="all", group=None)
        items = [MemoryLibraryItem(id=row["summary_id"], kind="story", title=row["title"],
                    text=row["content"], timestamp=row.get("display_timestamp"),
                    needs_review=row.get("review_state") == "pending_confirmation") for row in page["items"]]
        return MemoryLibraryPage(items=items, total=page["total"], limit=limit, offset=offset)
    if memory.l1 is None:
        raise HTTPException(503, "Memory events are unavailable")
    rows, count = await asyncio.gather(
        memory.l1.query_events(limit=limit, offset=offset, order_by="timestamp_desc",
                               include_metadata_json=False, include_embedding_fields=False,
                               l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES), exclude_event_types=None),
        memory.l1.count_events(l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES), exclude_event_types=None),
    )
    return MemoryLibraryPage(items=[_event(row) for row in rows], total=count, limit=limit, offset=offset)


@memory_router.get("/library/evidence/{event_id}", response_model=MemoryLibraryItem)
async def memory_library_evidence(event_id: str) -> MemoryLibraryItem:
    memory = dependencies._resolve_unified_memory()
    if memory is None or memory.l1 is None:
        raise HTTPException(503, "Memory events are unavailable")
    # The governed query applies forgetting and visibility rules to exact-ID reads.
    rows = await memory.l1.query_events(event_id=event_id, limit=1,
                                       l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES), exclude_event_types=None,
                                       include_metadata_json=False, include_embedding_fields=False)
    if not rows:
        raise HTTPException(404, "Memory evidence is unavailable")
    return _event(rows[0])
