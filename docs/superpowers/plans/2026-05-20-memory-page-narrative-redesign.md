# Memory Page Narrative Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the memory page from a developer-style L0–L4 admin surface into a focused, narrative-driven reading surface with a five-item product taxonomy (故事 / 章节 / 画像 / 回忆 / 治理), reusing existing L3 insights, L3 temporal summaries, L2 episodes, and the user profile projection.

**Architecture:** Three new backend endpoints (`GET /memory/stories`, `GET /memory/portrait/self`, `PATCH /memory/l3/summaries/{summary_id}/review`) compose existing stores — no schema changes. Frontend introduces five new top-level pages under `pages/memory-pages/`, refactors the sidebar to the new taxonomy, demotes the existing per-layer pages (`MemoryEventsPage`, `MemoryKnowledgePage`, `MemorySkillsPage`) under a collapsible "Developer view" inside Governance, and deletes the replaced pages (`MemoryOverviewPage`, `MemoryWorkbenchPage`, `MemoryReflectionPage`).

**Tech Stack:** FastAPI + aiosqlite (backend), React + react-router + react-i18next + Tailwind + Vitest + Testing Library (frontend).

**Reference:** Design spec at [docs/superpowers/specs/2026-05-20-memory-page-narrative-redesign-design.md](../specs/2026-05-20-memory-page-narrative-redesign-design.md).

---

## File Structure

### Backend — new

- `backend/src/magi/api/routers/memory/stories_routes.py` — unified story feed + review-state mutation
- `backend/src/magi/api/routers/memory/portrait_self_routes.py` — global self-portrait, no LLM rendering
- `backend/src/magi/memory/l3/storage/review_operations.py` — `set_review_state(summary_id, review_state, user_note)` mixin
- `backend/tests/api/test_memory_stories_routes.py` — story feed integration
- `backend/tests/api/test_memory_portrait_self_routes.py` — self-portrait integration
- `backend/tests/memory/l3/test_review_operations.py` — review_state persistence

### Backend — modified

- `backend/src/magi/api/routers/memory/__init__.py` — register the two new routers
- `backend/src/magi/memory/l3/storage/__init__.py` — wire `L3ReviewOperationsMixin` into the store

### Frontend — new

- `frontend/src/pages/memory-pages/MemoryStoryPage.tsx` — landing feed (replaces overview)
- `frontend/src/pages/memory-pages/MemoryEpisodesPage.tsx` — pinned + paginated episodes
- `frontend/src/pages/memory-pages/MemoryPortraitPage.tsx` — global "self" portrait
- `frontend/src/pages/memory-pages/MemoryRecallPage.tsx` — renamed recall (was workbench search)
- `frontend/src/pages/memory-pages/MemoryGovernancePage.tsx` — agency + developer subtree
- `frontend/src/components/memory/story/StoryCard.tsx`
- `frontend/src/components/memory/story/StoryDetailRail.tsx`
- `frontend/src/components/memory/episodes/EpisodeRow.tsx`
- `frontend/src/components/memory/portrait/PortraitSegment.tsx`
- `frontend/src/api/modules/memoryStories.ts` — story feed + review mutation client
- `frontend/src/api/modules/memoryPortraitSelf.ts` — global self portrait client
- `frontend/src/__tests__/memoryStoryPage.test.tsx`
- `frontend/src/__tests__/memoryEpisodesPage.test.tsx`
- `frontend/src/__tests__/memoryPortraitPage.test.tsx`
- `frontend/src/__tests__/memoryRecallPage.test.tsx`
- `frontend/src/__tests__/memoryGovernancePage.test.tsx`

### Frontend — modified

- `frontend/src/components/layout/Sidebar.tsx` — replace MEMORY_DESTINATIONS with the 5-item taxonomy
- `frontend/src/router/index.tsx` — new routes, redirects for old paths, dev-view route gate
- `frontend/src/i18n/locales/zh-CN/app.json` — new memory.* subtree
- `frontend/src/i18n/locales/en/app.json` — same in English
- `frontend/src/pages/memory-pages/index.ts` — export new pages, remove deleted pages
- `frontend/src/__tests__/sidebarNavigation.test.tsx` — assert new nav items
- `frontend/src/__tests__/appShellRouting.test.tsx` — update route assertions

### Frontend — deleted

- `frontend/src/pages/memory-pages/MemoryOverviewPage.tsx`
- `frontend/src/pages/memory-pages/MemoryWorkbenchPage.tsx`
- `frontend/src/pages/memory-pages/MemoryReflectionPage.tsx`
- `frontend/src/__tests__/useMemoryInitialLoadScope.test.tsx` (covers the overview hook, replaced by per-page tests)

`MemoryEventsPage.tsx`, `MemoryKnowledgePage.tsx`, `MemorySkillsPage.tsx` are kept and surfaced via Governance → 开发者视图.

---

## Phase 1 — Backend: Story Feed Endpoint

### Task 1: Story feed contract and listing

**Files:**
- Create: `backend/src/magi/api/routers/memory/stories_routes.py`
- Test: `backend/tests/api/test_memory_stories_routes.py`

The story feed unifies two existing data sources:
- L3 summaries with `summary_category` in `{state_change, contradiction, trend_shift, task_reflection, goal_refinement, preference_emergence, risk_escalation, milestone_review}` (insight-class)
- L3 summaries with `summary_category` in `{day, week, month, quarter, year}` (temporal-class)

Both already flow through `unified_memory.l3.list_summaries_by_category`. We compose, paginate, and order them.

- [ ] **Step 1: Write the failing test for the empty-store case**

Create `backend/tests/api/test_memory_stories_routes.py`:

```python
"""Integration tests for /api/memory/stories."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.stories_routes import build_router, override_unified_memory_for_test


@pytest.fixture
def app_factory():
    def _build():
        app = FastAPI()
        app.include_router(build_router(), prefix="/api/memory")
        return app
    return _build


def _stub_memory(insights=None, temporal=None):
    l3 = MagicMock()
    l3.list_summaries_by_category = AsyncMock(side_effect=lambda **kwargs: (
        list(insights or []) if "state_change" in kwargs["summary_categories"]
        else list(temporal or [])
    ))
    unified = MagicMock()
    unified.l3 = l3
    return unified


def test_empty_store_returns_empty_feed(app_factory):
    unified = _stub_memory(insights=[], temporal=[])
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
```

- [ ] **Step 2: Run the failing test**

Run: `cd backend && pytest tests/api/test_memory_stories_routes.py -v`
Expected: FAIL with "No module named 'magi.api.routers.memory.stories_routes'"

- [ ] **Step 3: Implement the minimal stories router**

Create `backend/src/magi/api/routers/memory/stories_routes.py`:

```python
"""GET /api/memory/stories — unified narrative feed."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...routers.memory.dependencies import _resolve_unified_memory

logger = logging.getLogger(__name__)

INSIGHT_CATEGORIES = [
    "state_change",
    "trend_shift",
    "conflict_resolution",
    "task_reflection",
    "goal_refinement",
    "preference_emergence",
    "risk_escalation",
    "milestone_review",
]

TEMPORAL_CATEGORIES = ["day", "week", "month", "quarter", "year"]


_memory_override: Any = None


@contextmanager
def override_unified_memory_for_test(unified_memory: Any):
    global _memory_override
    _memory_override = unified_memory
    try:
        yield
    finally:
        _memory_override = None


def _get_memory() -> Any:
    if _memory_override is not None:
        return _memory_override
    return _resolve_unified_memory()


def _row_to_story_item(row: dict[str, Any]) -> dict[str, Any]:
    """Project a raw L3 summary row into a story-feed item."""
    return {
        "summary_id": row.get("summary_id") or row.get("id"),
        "summary_type": row.get("summary_type"),
        "summary_category": row.get("summary_category"),
        "title": row.get("title") or _derive_title(row),
        "content": row.get("content") or "",
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "updated_at": row.get("updated_at"),
        "review_state": row.get("review_state") or "neutral",
        "insight_key": row.get("insight_key"),
        "insight_metadata": row.get("insight_metadata") or {},
        "evidence_event_count": int(row.get("source_event_count") or 0),
    }


def _derive_title(row: dict[str, Any]) -> str:
    category = str(row.get("summary_category") or "")
    if category in TEMPORAL_CATEGORIES:
        return f"{category}_summary"
    return category or "story"


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stories")
    async def list_stories(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        unified = _get_memory()
        if unified is None or unified.l3 is None:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        insights, temporal = await asyncio.gather(
            unified.l3.list_summaries_by_category(
                summary_categories=INSIGHT_CATEGORIES,
                limit=limit + offset + 50,
            ),
            unified.l3.list_summaries_by_category(
                summary_categories=TEMPORAL_CATEGORIES,
                limit=limit + offset + 50,
            ),
        )

        combined = [_row_to_story_item(r) for r in [*insights, *temporal]]
        combined.sort(
            key=lambda item: (
                0 if item["review_state"] == "pending_confirmation" else 1,
                -(item["period_end"] or item["updated_at"] or 0),
            )
        )
        sliced = combined[offset : offset + limit]
        return {
            "items": sliced,
            "total": len(combined),
            "limit": limit,
            "offset": offset,
        }

    return router
```

- [ ] **Step 4: Verify the empty-store test passes**

Run: `cd backend && pytest tests/api/test_memory_stories_routes.py::test_empty_store_returns_empty_feed -v`
Expected: PASS

- [ ] **Step 5: Add ordering and shape tests**

Append to `backend/tests/api/test_memory_stories_routes.py`:

```python
def test_proposed_insights_float_to_top(app_factory):
    insights = [{
        "summary_id": "ins-1",
        "summary_type": "insight",
        "summary_category": "state_change",
        "content": "你最近转向更安静的播放选择",
        "period_end": 100.0,
        "updated_at": 100.0,
        "review_state": "pending_confirmation",
        "source_event_count": 8,
    }]
    temporal = [{
        "summary_id": "tmp-1",
        "summary_type": "temporal",
        "summary_category": "week",
        "content": "本周以阅读为主",
        "period_end": 200.0,
        "updated_at": 200.0,
        "review_state": "neutral",
        "source_event_count": 14,
    }]
    unified = _stub_memory(insights=insights, temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 20})
    body = resp.json()
    assert [item["summary_id"] for item in body["items"]] == ["ins-1", "tmp-1"]
    assert body["items"][0]["review_state"] == "pending_confirmation"
    assert body["items"][0]["evidence_event_count"] == 8


def test_pagination_limits_results(app_factory):
    temporal = [
        {"summary_id": f"t-{i}", "summary_type": "temporal", "summary_category": "day",
         "content": "", "period_end": float(i), "updated_at": float(i),
         "review_state": "neutral", "source_event_count": 1}
        for i in range(5)
    ]
    unified = _stub_memory(insights=[], temporal=temporal)
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.get("/api/memory/stories", params={"limit": 2, "offset": 1})
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["summary_id"] == "t-3"  # second-newest after offset 1
    assert body["total"] == 5
```

- [ ] **Step 6: Run all stories-route tests**

Run: `cd backend && pytest tests/api/test_memory_stories_routes.py -v`
Expected: all three tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/api/routers/memory/stories_routes.py backend/tests/api/test_memory_stories_routes.py
git commit -m "feat(memory/stories): unified story-feed endpoint composing L3 insights + temporal summaries"
```

### Task 2: Wire the stories router into the memory router group

**Files:**
- Modify: `backend/src/magi/api/routers/memory/__init__.py`

- [ ] **Step 1: Locate the existing router registration**

Run: `grep -n "include_router\|build_router\|portrait_routes" backend/src/magi/api/routers/memory/__init__.py`
Expected: shows where the portrait router is mounted (the integration point).

- [ ] **Step 2: Register the stories router beside the others**

In `backend/src/magi/api/routers/memory/__init__.py`, find the block that builds and includes `portrait_routes.build_router()` (or equivalent for the other sub-routers). Add immediately after it:

```python
from . import stories_routes  # noqa: E402

memory_router.include_router(stories_routes.build_router())
```

If the file uses a single `from .X import build_router` pattern, follow that pattern instead. The router prefix matches the other memory sub-routes (`/memory/...`); the path inside `stories_routes` already starts with `/stories`.

- [ ] **Step 3: Run a smoke test through the main API surface**

Run: `cd backend && pytest tests/api/test_memory_stories_routes.py -v`
Expected: PASS (still using the in-test FastAPI app, but the import path now resolves through the real package).

Then run: `cd backend && python -c "from magi.api.routers.memory import memory_router; print([r.path for r in memory_router.routes if 'stories' in r.path])"`
Expected: prints `['/stories']` or similar.

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/api/routers/memory/__init__.py
git commit -m "feat(memory/stories): register stories router under memory router group"
```

### Task 3: Review-state mutation endpoint

**Files:**
- Create: `backend/src/magi/memory/l3/storage/review_operations.py`
- Modify: `backend/src/magi/memory/l3/storage/__init__.py`
- Modify: `backend/src/magi/api/routers/memory/stories_routes.py`
- Test: `backend/tests/memory/l3/test_review_operations.py`
- Test: `backend/tests/api/test_memory_stories_routes.py`

- [ ] **Step 1: Write the failing test for the store-level mixin**

Create `backend/tests/memory/l3/test_review_operations.py`:

```python
"""Unit tests for L3 review-state operations."""

from __future__ import annotations

import os
import tempfile

import pytest

from magi.memory.l3.summary_store import L3SummaryStore


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "l3.db")
    s = L3SummaryStore(db_path=db_path)
    await s.initialize()
    return s


async def _insert_summary(store, summary_id: str, review_state: str = "neutral") -> None:
    # Use the store's existing persist path to seed a row.
    from magi.memory.l3.models import L3Candidate
    candidate = L3Candidate(
        content="seed",
        source_event_ids=[],
        summary_category="state_change",
        summary_type="insight",
        review_state=review_state,
    )
    await store.persist_candidate(candidate=candidate, summary_id=summary_id)


@pytest.mark.asyncio
async def test_set_review_state_updates_row(store):
    await _insert_summary(store, "sum-1", review_state="pending_confirmation")
    ok = await store.set_review_state(summary_id="sum-1", review_state="confirmed", user_note=None)
    assert ok is True
    row = await store.get_summary_by_id("sum-1")
    assert row["review_state"] == "confirmed"


@pytest.mark.asyncio
async def test_set_review_state_returns_false_for_unknown_id(store):
    ok = await store.set_review_state(summary_id="nope", review_state="confirmed", user_note=None)
    assert ok is False


@pytest.mark.asyncio
async def test_set_review_state_persists_user_note(store):
    await _insert_summary(store, "sum-2")
    await store.set_review_state(summary_id="sum-2", review_state="confirmed", user_note="me too")
    row = await store.get_summary_by_id("sum-2")
    assert (row.get("insight_metadata") or {}).get("user_note") == "me too"
```

- [ ] **Step 2: Run the failing test**

Run: `cd backend && pytest tests/memory/l3/test_review_operations.py -v`
Expected: FAIL with "L3SummaryStore has no attribute 'set_review_state'".

If `persist_candidate` or `get_summary_by_id` is named differently in the actual store, adapt the test to the real method names — run `grep -n "def persist\|def get_summary" backend/src/magi/memory/l3/**/*.py` to find them.

- [ ] **Step 3: Implement the review-state mixin**

Create `backend/src/magi/memory/l3/storage/review_operations.py`:

```python
"""L3 review-state mutation operations."""

from __future__ import annotations

import json
import time
from typing import Any, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async


ALLOWED_REVIEW_STATES = (
    "neutral",
    "pending_confirmation",
    "confirmed",
    "rejected",
    "archived",
)


class _ReviewHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


class L3ReviewOperationsMixin:
    """Write methods for updating review state and user-attached notes."""

    async def set_review_state(
        self,
        *,
        summary_id: str,
        review_state: str,
        user_note: Optional[str] = None,
    ) -> bool:
        if review_state not in ALLOWED_REVIEW_STATES:
            raise ValueError(f"invalid review_state: {review_state}")
        host = cast(_ReviewHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT insight_metadata FROM summaries WHERE summary_id = ?",
                (summary_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return False
            metadata = _decode_metadata(row["insight_metadata"])
            if user_note is not None:
                metadata["user_note"] = user_note
            await db.execute(
                """
                UPDATE summaries
                SET review_state = ?, insight_metadata = ?, updated_at = ?
                WHERE summary_id = ?
                """,
                (
                    review_state,
                    json.dumps(metadata, ensure_ascii=False),
                    time.time(),
                    summary_id,
                ),
            )
            await db.commit()
        return True


def _decode_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return {}
    return {}


__all__ = ["L3ReviewOperationsMixin", "ALLOWED_REVIEW_STATES"]
```

- [ ] **Step 4: Wire the mixin into the L3 summary store class**

Open `backend/src/magi/memory/l3/storage/__init__.py` (or the file that builds the `L3SummaryStore` class). Add the new mixin to the base-class tuple beside the other persistence mixins.

Pattern to follow (the existing file already composes mixins this way):

```python
from .review_operations import L3ReviewOperationsMixin
# add L3ReviewOperationsMixin to the bases of L3SummaryStore alongside the existing mixins
```

If the actual store class is declared in `backend/src/magi/memory/l3/summary_store.py`, edit there instead. Use `grep -n "class L3SummaryStore" backend/src/magi/memory/l3/` to find the declaration.

- [ ] **Step 5: Verify the store-level tests pass**

Run: `cd backend && pytest tests/memory/l3/test_review_operations.py -v`
Expected: all three tests PASS.

- [ ] **Step 6: Add the HTTP layer test**

Append to `backend/tests/api/test_memory_stories_routes.py`:

```python
def test_review_state_patch_updates_summary(app_factory):
    l3 = MagicMock()
    l3.set_review_state = AsyncMock(return_value=True)
    unified = MagicMock(); unified.l3 = l3
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.patch(
            "/api/memory/stories/sum-1/review",
            json={"review_state": "confirmed", "user_note": "yes"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    l3.set_review_state.assert_awaited_once_with(
        summary_id="sum-1", review_state="confirmed", user_note="yes",
    )


def test_review_state_patch_404_for_unknown(app_factory):
    l3 = MagicMock()
    l3.set_review_state = AsyncMock(return_value=False)
    unified = MagicMock(); unified.l3 = l3
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.patch("/api/memory/stories/nope/review",
                            json={"review_state": "confirmed"})
    assert resp.status_code == 404


def test_review_state_patch_rejects_invalid_state(app_factory):
    unified = MagicMock(); unified.l3 = MagicMock()
    with override_unified_memory_for_test(unified):
        client = TestClient(app_factory())
        resp = client.patch("/api/memory/stories/sum-1/review",
                            json={"review_state": "bogus"})
    assert resp.status_code == 422
```

- [ ] **Step 7: Add the HTTP route**

In `backend/src/magi/api/routers/memory/stories_routes.py`, inside `build_router()`, append:

```python
    from pydantic import BaseModel, Field

    class ReviewPatch(BaseModel):
        review_state: str = Field(..., min_length=1)
        user_note: str | None = None

    @router.patch("/stories/{summary_id}/review")
    async def patch_review_state(summary_id: str, payload: ReviewPatch) -> dict[str, Any]:
        from ....memory.l3.storage.review_operations import ALLOWED_REVIEW_STATES
        if payload.review_state not in ALLOWED_REVIEW_STATES:
            raise HTTPException(status_code=422, detail="invalid_review_state")
        unified = _get_memory()
        if unified is None or unified.l3 is None:
            raise HTTPException(status_code=503, detail="memory_unavailable")
        ok = await unified.l3.set_review_state(
            summary_id=summary_id,
            review_state=payload.review_state,
            user_note=payload.user_note,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="summary_not_found")
        return {"ok": True, "summary_id": summary_id, "review_state": payload.review_state}
```

- [ ] **Step 8: Run the full story-routes suite**

Run: `cd backend && pytest tests/api/test_memory_stories_routes.py tests/memory/l3/test_review_operations.py -v`
Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/src/magi/memory/l3/storage/review_operations.py \
        backend/src/magi/memory/l3/storage/__init__.py \
        backend/src/magi/api/routers/memory/stories_routes.py \
        backend/tests/api/test_memory_stories_routes.py \
        backend/tests/memory/l3/test_review_operations.py
git commit -m "feat(memory/stories): PATCH /stories/{id}/review for confirm/reject/archive"
```

---

## Phase 2 — Backend: Self-Portrait Endpoint

### Task 4: Build the self-portrait assembler

**Files:**
- Create: `backend/src/magi/api/routers/memory/portrait_self_routes.py`
- Test: `backend/tests/api/test_memory_portrait_self_routes.py`

The self-portrait does NOT go through the LLM rendering pipeline used by `/memory/portrait`. It assembles `PortraitObservation` records directly from:
- `UserProfileProjectionRepository.get(user_id)` — identity, communication, preferences, state
- L2 ToM snapshot via `unified_memory.l2.get_latest_tom_snapshot(entity_id)` — Magi's overall impression
- L2 self-assertions via `unified_memory.l2.list_self_assertions(user_id, limit=50)` — reviewable per-trait facts

If a query helper doesn't exist (e.g. `list_self_assertions`), use the closest existing read — `list_assertions(entity_id=...)` — and filter to the user's self entity.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/test_memory_portrait_self_routes.py`:

```python
"""Integration tests for /api/memory/portrait/self."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_self_routes import (
    build_router,
    override_dependencies_for_test,
)


def _app():
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/memory")
    return app


def test_cold_start_when_no_projection_and_no_snapshot():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=None)
    l2 = MagicMock()
    l2.get_latest_tom_snapshot = AsyncMock(return_value=None)
    l2.list_assertions = AsyncMock(return_value={"items": []})
    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_cold_start"] is True
    assert body["cold_start_reason"] == "no_observations"
    assert body["observations"] == []
    assert body["session_id"] == ""


def test_returns_observations_from_projection_and_snapshot():
    profile_repo = MagicMock()
    profile_repo.get = AsyncMock(return_value=MagicMock(
        user_id="u1",
        display_name="Asuka",
        preferred_form_of_address="阿明",
        real_name="",
        home_location="杭州",
        communication={"response_style.preferred": "concise"},
        identity={},
        preferences={"music.genre": "ambient"},
        state={"focus_mode": "deep_work"},
        completeness_score=0.4,
        refreshed_at=100.0,
    ))
    l2 = MagicMock()
    l2.get_latest_tom_snapshot = AsyncMock(return_value={
        "core_traits": "好奇、专注、对工程细节敏感",
        "preferences_history": [],
        "updated_at": 200.0,
    })
    l2.list_assertions = AsyncMock(return_value={"items": []})
    with override_dependencies_for_test(profile_repo=profile_repo, l2=l2):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait/self", params={"user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_cold_start"] is False
    kinds = [obs["kind"] for obs in body["observations"]]
    assert "assertion" in kinds  # from projection
    assert "reflection" in kinds  # from tom snapshot
    texts = " ".join(obs["text"] for obs in body["observations"])
    assert "杭州" in texts or "阿明" in texts
```

- [ ] **Step 2: Run the failing test**

Run: `cd backend && pytest tests/api/test_memory_portrait_self_routes.py -v`
Expected: FAIL with "No module named 'magi.api.routers.memory.portrait_self_routes'".

- [ ] **Step 3: Implement the route**

Create `backend/src/magi/api/routers/memory/portrait_self_routes.py`:

```python
"""GET /api/memory/portrait/self — global self-portrait without LLM rendering."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query

from ....memory.portrait.contracts import PortraitObservation, PortraitPayload
from ....memory.provider import get_unified_memory
from ....user_profile.projection_repository import UserProfileProjectionRepository


logger = logging.getLogger(__name__)


_profile_repo_override: Any = None
_l2_override: Any = None


@contextmanager
def override_dependencies_for_test(*, profile_repo: Any = None, l2: Any = None):
    global _profile_repo_override, _l2_override
    _profile_repo_override = profile_repo
    _l2_override = l2
    try:
        yield
    finally:
        _profile_repo_override = None
        _l2_override = None


def _resolve_profile_repo():
    if _profile_repo_override is not None:
        return _profile_repo_override
    unified = get_unified_memory()
    db_path = str(getattr(getattr(unified, "l2", None), "db_path", "") or "")
    if not db_path:
        return None
    return UserProfileProjectionRepository(db_path)


def _resolve_l2():
    if _l2_override is not None:
        return _l2_override
    unified = get_unified_memory()
    return getattr(unified, "l2", None) if unified else None


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/portrait/self")
    async def get_self_portrait(
        user_id: str = Query(..., min_length=1),
    ) -> dict[str, Any]:
        profile_repo = _resolve_profile_repo()
        l2 = _resolve_l2()
        observations: list[PortraitObservation] = []

        projection = None
        if profile_repo is not None:
            try:
                projection = await profile_repo.get(user_id)
            except Exception as exc:
                logger.debug("self portrait: profile lookup failed: %s", exc)
        observations.extend(_observations_from_projection(projection))

        snapshot = None
        if l2 is not None:
            try:
                snapshot = await l2.get_latest_tom_snapshot(entity_id=f"user:{user_id}")
            except Exception as exc:
                logger.debug("self portrait: tom snapshot lookup failed: %s", exc)
        observations.extend(_observations_from_snapshot(snapshot))

        if l2 is not None:
            try:
                assertion_page = await l2.list_assertions(
                    entity_id=f"user:{user_id}", limit=50, offset=0,
                )
            except Exception as exc:
                logger.debug("self portrait: assertion lookup failed: %s", exc)
                assertion_page = None
            if assertion_page:
                observations.extend(_observations_from_assertions(assertion_page))

        is_cold_start = len(observations) == 0
        payload = PortraitPayload(
            session_id="",
            persona_id="",
            topic="self",
            generated_at=int(time.time()),
            observations=observations,
            is_cold_start=is_cold_start,
            cold_start_line=("Magi 还没有从你的记忆里得出关于你的整体印象。" if is_cold_start else None),
            cold_start_reason=("no_observations" if is_cold_start else None),
        )
        return payload.to_dict()

    return router


def _observations_from_projection(projection: Any) -> list[PortraitObservation]:
    if projection is None:
        return []

    facts: list[tuple[str, str]] = []
    if projection.real_name:
        facts.append((f"你叫 {projection.real_name}", "real_name"))
    if projection.preferred_form_of_address:
        facts.append((f"称呼你「{projection.preferred_form_of_address}」", "preferred_form_of_address"))
    if projection.home_location:
        facts.append((f"住在{projection.home_location}", "home_location"))
    for key, value in (projection.preferences or {}).items():
        facts.append((f"偏好：{key} = {value}", f"preference:{key}"))
    for key, value in (projection.communication or {}).items():
        facts.append((f"沟通风格：{key} = {value}", f"communication:{key}"))
    for key, value in (projection.state or {}).items():
        facts.append((f"近期状态：{key} = {value}", f"state:{key}"))

    return [
        PortraitObservation(
            kind="assertion",
            text=text,
            basis_count=1,
            basis_summary="user_profile_projection",
            basis_refs=[ref],
        )
        for text, ref in facts
    ]


def _observations_from_snapshot(snapshot: dict[str, Any] | None) -> list[PortraitObservation]:
    if not snapshot:
        return []
    text = str(snapshot.get("core_traits") or "").strip()
    if not text:
        return []
    return [PortraitObservation(
        kind="reflection",
        text=text,
        basis_count=int(snapshot.get("evidence_count") or 1),
        basis_summary="L2 ToM snapshot",
        basis_refs=[str(snapshot.get("snapshot_id") or "tom-latest")],
    )]


def _observations_from_assertions(page: dict[str, Any]) -> list[PortraitObservation]:
    items = page.get("items") if isinstance(page, dict) else None
    if not items:
        return []
    obs: list[PortraitObservation] = []
    for item in items[:20]:
        trait = str(item.get("trait_name") or item.get("predicate") or "")
        value = str(item.get("value") or item.get("trait_value") or "")
        if not trait or not value:
            continue
        obs.append(PortraitObservation(
            kind="assertion",
            text=f"{trait}: {value}",
            basis_count=int(item.get("evidence_count") or 1),
            basis_summary="L2 assertion",
            basis_refs=[str(item.get("assertion_id") or "")],
        ))
    return obs
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && pytest tests/api/test_memory_portrait_self_routes.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Register the router**

Open `backend/src/magi/api/routers/memory/__init__.py` and add, beside the stories registration from Task 2:

```python
from . import portrait_self_routes  # noqa: E402

memory_router.include_router(portrait_self_routes.build_router())
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/api/routers/memory/portrait_self_routes.py \
        backend/src/magi/api/routers/memory/__init__.py \
        backend/tests/api/test_memory_portrait_self_routes.py
git commit -m "feat(memory/portrait): /portrait/self endpoint composing projection + ToM snapshot"
```

---

## Phase 3 — Frontend: API Clients, i18n, Sidebar, Routes

### Task 5: Story-feed API client and types

**Files:**
- Create: `frontend/src/api/modules/memoryStories.ts`

- [ ] **Step 1: Write the client**

Create `frontend/src/api/modules/memoryStories.ts`:

```typescript
import { api, unwrapGatewayPayload } from '../client';

export type StoryReviewState =
  | 'neutral'
  | 'pending_confirmation'
  | 'confirmed'
  | 'rejected'
  | 'archived';

export type StorySummaryCategory = string;

export interface StoryItem {
  summary_id: string;
  summary_type: 'insight' | 'temporal' | 'thematic' | string;
  summary_category: StorySummaryCategory;
  title: string;
  content: string;
  period_start: number | null;
  period_end: number | null;
  updated_at: number;
  review_state: StoryReviewState;
  insight_key: string | null;
  insight_metadata: Record<string, unknown>;
  evidence_event_count: number;
}

export interface StoryFeedPayload {
  items: StoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface StoryReviewPatch {
  review_state: StoryReviewState;
  user_note?: string | null;
}

export const memoryStoriesApi = {
  list: async (params?: { limit?: number; offset?: number }): Promise<StoryFeedPayload> => {
    const response = await api.get<StoryFeedPayload>('/memory/stories', { params });
    return unwrapGatewayPayload(response);
  },
  review: async (summaryId: string, patch: StoryReviewPatch): Promise<{ ok: true; summary_id: string; review_state: StoryReviewState }> => {
    const response = await api.patch(`/memory/stories/${summaryId}/review`, patch);
    return unwrapGatewayPayload(response);
  },
};
```

- [ ] **Step 2: Verify type-check**

Run: `cd frontend && npx tsc --noEmit src/api/modules/memoryStories.ts`
Expected: no errors. (If the project doesn't allow per-file tsc, run the project's normal lint/typecheck: `npm run typecheck` from `frontend/`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/modules/memoryStories.ts
git commit -m "feat(frontend/memory): story-feed API client"
```

### Task 6: Self-portrait API client

**Files:**
- Create: `frontend/src/api/modules/memoryPortraitSelf.ts`

- [ ] **Step 1: Write the client**

Create `frontend/src/api/modules/memoryPortraitSelf.ts`:

```typescript
import { api, unwrapGatewayPayload } from '../client';
import type { PortraitPayload } from './memoryPortrait';

export const memoryPortraitSelfApi = {
  get: async (userId: string): Promise<PortraitPayload> => {
    const response = await api.get<PortraitPayload>('/memory/portrait/self', {
      params: { user_id: userId },
    });
    return unwrapGatewayPayload(response);
  },
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/modules/memoryPortraitSelf.ts
git commit -m "feat(frontend/memory): self-portrait API client reusing PortraitPayload"
```

### Task 7: i18n keys for the new memory taxonomy

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`

- [ ] **Step 1: Replace the `memory.nav` block in zh-CN**

In `frontend/src/i18n/locales/zh-CN/app.json`, find the `"memory": { "nav": {...} }` block (around line 2596). Replace the existing `nav` object with:

```json
    "nav": {
      "stories": "故事",
      "episodes": "章节",
      "portrait": "画像",
      "recall": "回忆",
      "governance": "治理",
      "devSubtreeLabel": "开发者视图",
      "dev": {
        "events": "原始事件 (L1)",
        "knowledge": "结构化知识 (L2)",
        "workbench": "工作台记忆 (L0)",
        "skills": "工具技能 (L4)",
        "stats": "存储统计"
      }
    },
```

- [ ] **Step 2: Add the new content blocks for each view in zh-CN**

In the same file, replace the existing `memory.overview` block with these five new blocks (the `memory.overview` content can be removed entirely):

```json
    "stories": {
      "title": "故事",
      "subtitle": "Magi 最近编织出的反思和阶段总结。",
      "emptyTitle": "还没有 Magi 关于你的反思",
      "emptyBody": "继续使用一段时间，这里会出现它对你的观察。",
      "evidenceChip": "{{count}} 条证据",
      "states": {
        "pending_confirmation": "待确认",
        "confirmed": "已确认",
        "rejected": "已拒绝",
        "archived": "已收起",
        "neutral": ""
      },
      "actions": {
        "confirm": "确认",
        "reject": "拒绝",
        "archive": "收起",
        "addNote": "备注",
        "viewEvidence": "查看证据"
      },
      "categories": {
        "state_change": "状态变化",
        "trend_shift": "趋势变化",
        "conflict_resolution": "冲突调和",
        "task_reflection": "任务反思",
        "goal_refinement": "目标更新",
        "preference_emergence": "偏好浮现",
        "risk_escalation": "风险升级",
        "milestone_review": "里程碑回顾",
        "day": "本日总结",
        "week": "本周总结",
        "month": "本月总结",
        "quarter": "本季度总结",
        "year": "本年度总结"
      },
      "detailRail": {
        "evidenceTitle": "证据",
        "notePlaceholder": "你想给这个反思加个备注吗？",
        "savedNote": "备注已保存"
      }
    },
    "episodes": {
      "title": "章节",
      "subtitle": "你被命名、标注、置顶的经历片段。",
      "pinnedSection": "置顶",
      "recentSection": "最近",
      "emptyTitle": "还没有可读的章节",
      "emptyBody": "经历会随着对话和活动累积成章节。",
      "filters": {
        "all": "全部",
        "activity": "活动",
        "visit": "拜访",
        "session": "会话",
        "conversation": "对话"
      },
      "actions": {
        "pin": "置顶",
        "unpin": "取消置顶",
        "rename": "重命名",
        "annotate": "备注",
        "forget": "遗忘"
      }
    },
    "portrait": {
      "title": "画像",
      "subtitle": "Magi 眼中的你。",
      "segments": {
        "identity": "身份",
        "state": "当下",
        "preferences": "偏好",
        "relationships": "关系",
        "impression": "Magi 对你的总体印象"
      },
      "coldStartFallback": "Magi 还没有从你的记忆里得出关于你的整体印象。继续使用，这里会逐渐丰满。"
    },
    "recall": {
      "title": "回忆",
      "subtitle": "用自然语言把过去翻出来。",
      "searchPlaceholder": "想找一段对话、一个名字、一件做过的事…",
      "modes": {
        "auto": "智能",
        "events": "你说过 / 做过的事",
        "knowledge": "一句具体的事实",
        "state": "你现在的状态",
        "episodes": "一段经历",
        "summaries": "Magi 的总结",
        "skills": "Magi 学到的做事方式"
      },
      "advancedToggle": "调试细节",
      "noResults": "没找到合适的记忆，可以换一个更具体的词。"
    },
    "governance": {
      "title": "治理",
      "subtitle": "可审阅、可纠正、可遗忘的记忆控制台。",
      "sections": {
        "pendingReview": "待审阅",
        "corrected": "修正过的事实",
        "forget": "遗忘",
        "privacy": "隐私范围",
        "developer": "开发者视图"
      },
      "pendingReviewBody": "Magi 还没确认的反思会在这里等待你过一遍。",
      "developerBody": "原始事件、L2 结构化知识、L0 工作台和 L4 工具记忆都在这里。",
      "storageTitle": "存储统计",
      "storageBody": "当前共有 {{total}} 条记忆，占用 {{size}}。"
    }
```

- [ ] **Step 3: Same edits for English locale**

In `frontend/src/i18n/locales/en/app.json`, find the corresponding `memory.nav` and `memory.overview` blocks and replace them with English equivalents. Use the same key structure as zh-CN; example labels:

```json
    "nav": {
      "stories": "Stories",
      "episodes": "Chapters",
      "portrait": "Portrait",
      "recall": "Recall",
      "governance": "Governance",
      "devSubtreeLabel": "Developer view",
      "dev": {
        "events": "Raw events (L1)",
        "knowledge": "Structured knowledge (L2)",
        "workbench": "Working memory (L0)",
        "skills": "Procedural skills (L4)",
        "stats": "Storage stats"
      }
    },
```

Fill in the rest by translating each zh-CN value. Keep the same JSON keys exactly. If unsure of an English string for a Chinese term, use the closest existing label from the spec.

- [ ] **Step 4: Verify JSON parses cleanly**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/locales/zh-CN/app.json', 'utf8')); JSON.parse(require('fs').readFileSync('src/i18n/locales/en/app.json', 'utf8')); console.log('OK')"`
Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json
git commit -m "i18n(memory): new five-item taxonomy keys for stories/episodes/portrait/recall/governance"
```

### Task 8: Refactor the sidebar to the five-item taxonomy

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Update MEMORY_DESTINATIONS**

In `frontend/src/components/layout/Sidebar.tsx`, replace the `MEMORY_DESTINATIONS` constant (currently at line 43-50) with:

```typescript
const MEMORY_DESTINATIONS = [
  { key: 'stories', path: '/memory/stories' },
  { key: 'episodes', path: '/memory/episodes' },
  { key: 'portrait', path: '/memory/portrait' },
  { key: 'recall', path: '/memory/recall' },
  { key: 'governance', path: '/memory/governance' },
] as const;
```

- [ ] **Step 2: Update the default-memory navigate target**

Find every `navigate('/memory/overview')` call in the same file (lines around 364 and 496) and replace with `navigate('/memory/stories')`. There are two such sites — update both.

- [ ] **Step 3: Update the legacy `/events` mapping**

In the `renderMemoryPanel` function (around line 486), the line:

```typescript
const destinationActive =
  location.pathname === item.path ||
  (item.path === '/memory/overview' && location.pathname === '/events');
```

becomes:

```typescript
const destinationActive =
  location.pathname === item.path ||
  (item.path === '/memory/stories' && (location.pathname === '/events' || location.pathname === '/memory/overview'));
```

- [ ] **Step 4: Update isMemoryRoute**

The `isMemoryRoute` derivation (line 89) already covers `/memory/...`. No change needed — only verify by reading once.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(frontend/memory): sidebar five-item taxonomy (stories/episodes/portrait/recall/governance)"
```

### Task 9: Update router with new routes and redirects

**Files:**
- Modify: `frontend/src/router/index.tsx`

- [ ] **Step 1: Replace memory route children**

In `frontend/src/router/index.tsx`, find the `path: 'memory'` block (line 162) and replace the `children` array with:

```typescript
        children: [
          { index: true, element: <Navigate to="/memory/stories" replace /> },
          { path: 'overview', element: <Navigate to="/memory/stories" replace /> },
          { path: 'workbench', element: <Navigate to="/memory/recall" replace /> },
          { path: 'reflection', element: <Navigate to="/memory/stories" replace /> },
          {
            path: 'stories',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryStoryPage />
              </React.Suspense>
            ),
          },
          {
            path: 'episodes',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryEpisodesPage />
              </React.Suspense>
            ),
          },
          {
            path: 'portrait',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryPortraitPage />
              </React.Suspense>
            ),
          },
          {
            path: 'recall',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryRecallPage />
              </React.Suspense>
            ),
          },
          {
            path: 'governance',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryGovernancePage />
              </React.Suspense>
            ),
          },
          {
            path: 'events',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryEventsPage />
              </React.Suspense>
            ),
          },
          {
            path: 'knowledge',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemoryKnowledgePage />
              </React.Suspense>
            ),
          },
          {
            path: 'skills',
            element: (
              <React.Suspense fallback={<LoadingFallback />}>
                <MemorySkillsPage />
              </React.Suspense>
            ),
          },
        ],
```

- [ ] **Step 2: Update the lazy imports**

At the top of the same file (around lines 17–34), replace the memory imports with:

```typescript
const MemoryStoryPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryStoryPage }))
);
const MemoryEpisodesPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryEpisodesPage }))
);
const MemoryPortraitPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryPortraitPage }))
);
const MemoryRecallPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryRecallPage }))
);
const MemoryGovernancePage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryGovernancePage }))
);
const MemoryEventsPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryEventsPage }))
);
const MemoryKnowledgePage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemoryKnowledgePage }))
);
const MemorySkillsPage = React.lazy(() =>
  import('../pages/memory-pages').then((m) => ({ default: m.MemorySkillsPage }))
);
```

- [ ] **Step 3: Update the `/events` top-level redirect**

Find the existing `path: 'events'` block at the top level (around line 154) — it currently renders `MemoryOverviewPage`. Change it to redirect:

```typescript
      {
        path: 'events',
        element: <Navigate to="/memory/stories" replace />,
      },
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.tsx
git commit -m "feat(frontend/memory): router updates — new routes + legacy redirects"
```

### Task 10: Update sidebar navigation test

**Files:**
- Modify: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Locate any references to old memory nav keys**

Run: `grep -n "memory.nav\|/memory/overview\|/memory/workbench\|/memory/reflection" frontend/src/__tests__/sidebarNavigation.test.tsx`
Expected: shows the lines that need updating.

- [ ] **Step 2: Update the assertions**

In `frontend/src/__tests__/sidebarNavigation.test.tsx`, replace any assertion about old memory destinations with assertions for the five new items. Add the following test case at the end of the `describe` block (replacing any existing memory-section test if duplicate):

```typescript
it('shows the five-item memory taxonomy when the memory panel is open', async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/chat']}>
      <Sidebar />
    </MemoryRouter>,
  );
  await user.click(screen.getByRole('button', { name: /memory/i }));
  expect(screen.getByRole('button', { name: '故事' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '章节' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '画像' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '回忆' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '治理' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '记忆工作台' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '工具技能记忆' })).not.toBeInTheDocument();
});
```

If the test file currently asserts on English labels, mirror the same names from `en/app.json` instead.

- [ ] **Step 3: Run the test**

Run: `cd frontend && npm test -- sidebarNavigation.test.tsx --run`
Expected: PASS.

If it fails because the test was relying on rendering the old `MEMORY_DESTINATIONS`, fix the assertion to match what the sidebar now renders (the new keys). The test must read the new labels.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "test(frontend/memory): sidebar nav test asserts five-item taxonomy"
```

---

## Phase 4 — Frontend: Stories Page

### Task 11: StoryCard component

**Files:**
- Create: `frontend/src/components/memory/story/StoryCard.tsx`

- [ ] **Step 1: Create the component**

Create directory `frontend/src/components/memory/story/` then `StoryCard.tsx`:

```typescript
import { useTranslation } from 'react-i18next';
import { Check, X, Archive, MessageSquare, ChevronRight } from 'lucide-react';
import type { StoryItem, StoryReviewState } from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface StoryCardProps {
  story: StoryItem;
  onConfirm: () => void;
  onReject: () => void;
  onArchive: () => void;
  onOpenDetail: () => void;
}

const stateToneClass = (state: StoryReviewState): string => {
  switch (state) {
    case 'pending_confirmation':
      return 'border-[hsl(var(--memory-accent)/0.4)] bg-[hsl(var(--memory-accent-soft)/0.5)]';
    case 'rejected':
    case 'archived':
      return 'opacity-60 border-[hsl(var(--memory-border)/0.35)] bg-[hsl(var(--memory-panel-elevated)/0.5)]';
    case 'confirmed':
      return 'border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.78)]';
    default:
      return 'border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.7)]';
  }
};

const formatPeriod = (start: number | null, end: number | null, locale: string): string => {
  const ts = end ?? start;
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(locale);
};

export const StoryCard = ({ story, onConfirm, onReject, onArchive, onOpenDetail }: StoryCardProps) => {
  const { t, i18n } = useTranslation('app');
  const categoryLabel = t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category });
  const stateLabel = t(`memory.stories.states.${story.review_state}`, { defaultValue: '' });
  const period = formatPeriod(story.period_start, story.period_end, i18n.language);

  return (
    <article
      data-testid={`story-card-${story.summary_id}`}
      className={cn('rounded-2xl border px-5 py-4 transition-colors', stateToneClass(story.review_state))}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2">
            <span className="rounded-sm bg-[hsl(var(--memory-panel-subtle)/0.7)] px-2 py-0.5 text-xs text-[hsl(var(--memory-muted))]">
              {categoryLabel}
            </span>
            {stateLabel ? (
              <span className="text-xs font-medium text-[hsl(var(--memory-accent))]">{stateLabel}</span>
            ) : null}
            {period ? <span className="text-xs text-[hsl(var(--memory-muted))]">{period}</span> : null}
          </div>
          <button
            type="button"
            onClick={onOpenDetail}
            className="text-left text-base font-semibold leading-6 text-[hsl(var(--memory-title))] hover:underline"
          >
            {story.title || story.content.slice(0, 80)}
          </button>
        </div>
        <Button variant="ghost" size="sm" onClick={onOpenDetail} aria-label={t('memory.stories.actions.viewEvidence')}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </header>

      <p className="mt-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
        {story.content}
      </p>

      <footer className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-[hsl(var(--memory-muted))]">
          {t('memory.stories.evidenceChip', { count: story.evidence_event_count })}
        </span>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={onConfirm} aria-label={t('memory.stories.actions.confirm')}>
            <Check className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onReject} aria-label={t('memory.stories.actions.reject')}>
            <X className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onArchive} aria-label={t('memory.stories.actions.archive')}>
            <Archive className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onOpenDetail} aria-label={t('memory.stories.actions.addNote')}>
            <MessageSquare className="h-4 w-4" />
          </Button>
        </div>
      </footer>
    </article>
  );
};

export default StoryCard;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/memory/story/StoryCard.tsx
git commit -m "feat(frontend/memory): StoryCard with review-state actions"
```

### Task 12: StoryDetailRail component

**Files:**
- Create: `frontend/src/components/memory/story/StoryDetailRail.tsx`

- [ ] **Step 1: Create the rail**

Create `frontend/src/components/memory/story/StoryDetailRail.tsx`:

```typescript
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { StoryItem } from '@/api/modules/memoryStories';
import { Button } from '@/components/ui/button';

interface StoryDetailRailProps {
  story: StoryItem | null;
  onClose: () => void;
  onSaveNote: (note: string) => Promise<void> | void;
}

export const StoryDetailRail = ({ story, onClose, onSaveNote }: StoryDetailRailProps) => {
  const { t, i18n } = useTranslation('app');
  const [note, setNote] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const existing = (story?.insight_metadata?.user_note ?? '') as string;
    setNote(existing);
    setSaved(false);
  }, [story?.summary_id]);

  if (!story) return null;

  const handleSave = async () => {
    await onSaveNote(note);
    setSaved(true);
  };

  const period = story.period_end ? new Date(story.period_end * 1000).toLocaleString(i18n.language) : '';

  return (
    <aside
      data-testid="story-detail-rail"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-lg flex-col border-l border-[hsl(var(--memory-border)/0.6)] bg-[hsl(var(--memory-panel-elevated)/0.96)] shadow-2xl"
    >
      <header className="flex items-start justify-between gap-3 border-b border-[hsl(var(--memory-divider)/0.6)] px-6 py-4">
        <div>
          <div className="text-xs text-[hsl(var(--memory-muted))]">
            {t(`memory.stories.categories.${story.summary_category}`, { defaultValue: story.summary_category })}
            {period ? ` · ${period}` : ''}
          </div>
          <h2 className="mt-1 text-lg font-semibold text-[hsl(var(--memory-title))]">{story.title || story.content.slice(0, 80)}</h2>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="close">
          <X className="h-4 w-4" />
        </Button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-4 text-sm leading-6 text-[hsl(var(--memory-body))]">
        <p>{story.content}</p>

        <div>
          <div className="text-xs font-medium text-[hsl(var(--memory-muted))]">
            {t('memory.stories.detailRail.evidenceTitle')}
          </div>
          <div className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.stories.evidenceChip', { count: story.evidence_event_count })}
          </div>
        </div>

        <div>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t('memory.stories.detailRail.notePlaceholder')}
            className="w-full rounded-sm border border-[hsl(var(--memory-input-border)/0.7)] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm"
            rows={4}
          />
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" onClick={handleSave}>{t('memory.stories.actions.addNote')}</Button>
            {saved ? (
              <span className="text-xs text-[hsl(var(--memory-muted))]">{t('memory.stories.detailRail.savedNote')}</span>
            ) : null}
          </div>
        </div>
      </div>
    </aside>
  );
};

export default StoryDetailRail;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/memory/story/StoryDetailRail.tsx
git commit -m "feat(frontend/memory): StoryDetailRail with note save"
```

### Task 13: MemoryStoryPage and tests

**Files:**
- Create: `frontend/src/pages/memory-pages/MemoryStoryPage.tsx`
- Create: `frontend/src/__tests__/memoryStoryPage.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/__tests__/memoryStoryPage.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';

import i18n from '@/i18n';
import { MemoryStoryPage } from '@/pages/memory-pages/MemoryStoryPage';
import { memoryStoriesApi } from '@/api/modules/memoryStories';

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: {
    list: vi.fn(),
    review: vi.fn(),
  },
}));

const renderPage = () =>
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>
        <MemoryStoryPage />
      </MemoryRouter>
    </I18nextProvider>
  );

beforeEach(() => {
  vi.clearAllMocks();
});

describe('MemoryStoryPage', () => {
  it('shows empty state when feed has no items', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/还没有 Magi 关于你的反思|No reflections yet/i)).toBeInTheDocument();
    });
  });

  it('renders story cards from the feed', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [{
        summary_id: 's1',
        summary_type: 'insight',
        summary_category: 'state_change',
        title: '你最近的播放变得更安静了',
        content: 'state change body',
        period_start: 1700000000,
        period_end: 1700100000,
        updated_at: 1700100000,
        review_state: 'pending_confirmation',
        insight_key: 'k',
        insight_metadata: {},
        evidence_event_count: 5,
      }],
      total: 1, limit: 20, offset: 0,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('你最近的播放变得更安静了')).toBeInTheDocument();
    });
    expect(screen.getByTestId('story-card-s1')).toBeInTheDocument();
  });

  it('confirms a story when the confirm button is clicked', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [{
        summary_id: 's1', summary_type: 'insight', summary_category: 'state_change',
        title: 't', content: 'c', period_start: 0, period_end: 1700100000,
        updated_at: 1700100000, review_state: 'pending_confirmation',
        insight_key: null, insight_metadata: {}, evidence_event_count: 1,
      }],
      total: 1, limit: 20, offset: 0,
    });
    vi.mocked(memoryStoriesApi.review).mockResolvedValue({ ok: true, summary_id: 's1', review_state: 'confirmed' });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByTestId('story-card-s1'));
    await user.click(screen.getByLabelText(/确认|Confirm/i));
    await waitFor(() => {
      expect(memoryStoriesApi.review).toHaveBeenCalledWith('s1', { review_state: 'confirmed' });
    });
  });
});
```

- [ ] **Step 2: Run the failing test**

Run: `cd frontend && npm test -- memoryStoryPage --run`
Expected: FAIL with "Cannot find module '@/pages/memory-pages/MemoryStoryPage'".

- [ ] **Step 3: Implement the page**

Create `frontend/src/pages/memory-pages/MemoryStoryPage.tsx`:

```typescript
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryStoriesApi, type StoryItem, type StoryReviewState } from '@/api/modules/memoryStories';
import StoryCard from '@/components/memory/story/StoryCard';
import StoryDetailRail from '@/components/memory/story/StoryDetailRail';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { LoadingSpinner } from '@/components/ui/loading-spinner';

export const MemoryStoryPage = () => {
  const { t } = useTranslation('app');
  const [items, setItems] = useState<StoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailStory, setDetailStory] = useState<StoryItem | null>(null);

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryStoriesApi.list({ limit: 30, offset: 0 });
      setItems(payload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchFeed();
  }, [fetchFeed]);

  const handleReview = useCallback(async (story: StoryItem, state: StoryReviewState, userNote?: string) => {
    await memoryStoriesApi.review(story.summary_id, { review_state: state, user_note: userNote ?? null });
    setItems((prev) => prev.map((it) => (
      it.summary_id === story.summary_id ? { ...it, review_state: state } : it
    )));
  }, []);

  const handleSaveNote = useCallback(async (note: string) => {
    if (!detailStory) return;
    await memoryStoriesApi.review(detailStory.summary_id, {
      review_state: detailStory.review_state,
      user_note: note,
    });
    setItems((prev) => prev.map((it) => (
      it.summary_id === detailStory.summary_id
        ? { ...it, insight_metadata: { ...it.insight_metadata, user_note: note } }
        : it
    )));
    setDetailStory((prev) => prev
      ? { ...prev, insight_metadata: { ...prev.insight_metadata, user_note: note } }
      : prev);
  }, [detailStory]);

  return (
    <MemoryPageFrame title={t('memory.stories.title')} description={t('memory.stories.subtitle')}>
      <section data-testid="memory-stories-feed" className="space-y-3">
        {loading ? (
          <div className={`${MEMORY_EMPTY_PANEL_CLASS} flex items-center gap-2`}>
            <LoadingSpinner className="h-4 w-4" />
          </div>
        ) : items.length === 0 ? (
          <div data-testid="memory-stories-empty" className={MEMORY_EMPTY_PANEL_CLASS}>
            <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.stories.emptyTitle')}</div>
            <p className="mt-1 text-sm">{t('memory.stories.emptyBody')}</p>
          </div>
        ) : (
          items.map((story) => (
            <StoryCard
              key={story.summary_id}
              story={story}
              onConfirm={() => void handleReview(story, 'confirmed')}
              onReject={() => void handleReview(story, 'rejected')}
              onArchive={() => void handleReview(story, 'archived')}
              onOpenDetail={() => setDetailStory(story)}
            />
          ))
        )}
      </section>

      <StoryDetailRail
        story={detailStory}
        onClose={() => setDetailStory(null)}
        onSaveNote={handleSaveNote}
      />
    </MemoryPageFrame>
  );
};

export default MemoryStoryPage;
```

- [ ] **Step 4: Export from the page barrel**

Open `frontend/src/pages/memory-pages/index.ts`. Add:

```typescript
export { MemoryStoryPage } from './MemoryStoryPage';
```

(Other exports to add will come in subsequent tasks; do not delete the existing exports yet.)

- [ ] **Step 5: Run the test**

Run: `cd frontend && npm test -- memoryStoryPage --run`
Expected: all three tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/memory-pages/MemoryStoryPage.tsx \
        frontend/src/pages/memory-pages/index.ts \
        frontend/src/__tests__/memoryStoryPage.test.tsx
git commit -m "feat(frontend/memory): MemoryStoryPage with review-state interactions"
```

---

## Phase 5 — Frontend: Episodes Page

### Task 14: Episodes page and row component

**Files:**
- Create: `frontend/src/components/memory/episodes/EpisodeRow.tsx`
- Create: `frontend/src/pages/memory-pages/MemoryEpisodesPage.tsx`
- Create: `frontend/src/__tests__/memoryEpisodesPage.test.tsx`
- Modify: `frontend/src/pages/memory-pages/index.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/memoryEpisodesPage.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';

import i18n from '@/i18n';
import { MemoryEpisodesPage } from '@/pages/memory-pages/MemoryEpisodesPage';
import { memoryApi } from '@/api/modules/memory';

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    annotateEpisode: vi.fn(),
    forgetEpisode: vi.fn(),
    listEpisodes: vi.fn(),
  },
}));

const renderPage = () =>
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>
        <MemoryEpisodesPage />
      </MemoryRouter>
    </I18nextProvider>
  );

beforeEach(() => vi.clearAllMocks());

describe('MemoryEpisodesPage', () => {
  it('renders pinned section above recent section', async () => {
    vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
      items: [
        { episode_id: 'e1', episode_type: 'activity', user_pinned: true, user_label: '搬家那周', summary: '',
          time_start: 1700000000, time_end: 1700100000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
          dominant_mode: null, status: 'active', user_note: '', label: '' },
        { episode_id: 'e2', episode_type: 'activity', user_pinned: false, user_label: null, summary: '昨天下午聊了一会',
          time_start: 1700200000, time_end: 1700300000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
          dominant_mode: null, status: 'active', user_note: '', label: '' },
      ],
      total: 2, limit: 50, offset: 0,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('搬家那周')).toBeInTheDocument();
    });
    const pinnedSection = screen.getByTestId('episodes-pinned');
    const recentSection = screen.getByTestId('episodes-recent');
    expect(pinnedSection.textContent).toContain('搬家那周');
    expect(recentSection.textContent).toContain('昨天下午聊了一会');
  });

  it('toggles pin on an episode', async () => {
    vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
      items: [{
        episode_id: 'e1', episode_type: 'session', user_pinned: false, user_label: null, summary: 'demo',
        time_start: 1700000000, time_end: 1700100000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
        dominant_mode: null, status: 'active', user_note: '', label: '',
      }],
      total: 1, limit: 50, offset: 0,
    });
    vi.mocked(memoryApi.annotateEpisode).mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText('demo'));
    await user.click(screen.getByLabelText(/置顶|Pin/i));
    await waitFor(() => {
      expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('e1', { user_pinned: true });
    });
  });
});
```

- [ ] **Step 2: Add the `listEpisodes` API method**

Open `frontend/src/api/modules/memory.ts`. Find the `// L2 Cognition` section (around line 488). Add:

```typescript
  listEpisodes: async (params?: PaginationParams & { episode_type?: string; status?: string }): Promise<PaginatedResponse<L2Episode>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Episode>>('/memory/l2/episodes', { params })),
```

If `L2Episode` is not yet exported from this module, add a re-export from the existing episode type defined elsewhere in the same file, or import it via the central memory types. Run `grep -n "L2Episode" frontend/src/api/modules/memory.ts` to locate the existing definition.

- [ ] **Step 3: Run the failing test**

Run: `cd frontend && npm test -- memoryEpisodesPage --run`
Expected: FAIL because `MemoryEpisodesPage` does not exist yet.

- [ ] **Step 4: Implement EpisodeRow**

Create `frontend/src/components/memory/episodes/EpisodeRow.tsx`:

```typescript
import { useTranslation } from 'react-i18next';
import { Pin, PinOff, Pencil, MessageSquare, Trash2 } from 'lucide-react';
import type { L2Episode } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';

interface EpisodeRowProps {
  episode: L2Episode;
  onTogglePin: () => void;
  onRename: () => void;
  onAnnotate: () => void;
  onForget: () => void;
}

export const EpisodeRow = ({ episode, onTogglePin, onRename, onAnnotate, onForget }: EpisodeRowProps) => {
  const { t, i18n } = useTranslation('app');
  const title = episode.user_label || episode.label || (episode.summary ? episode.summary.slice(0, 80) : episode.episode_id);
  const range = episode.time_start && episode.time_end
    ? `${new Date(episode.time_start * 1000).toLocaleDateString(i18n.language)} → ${new Date(episode.time_end * 1000).toLocaleDateString(i18n.language)}`
    : '';

  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.7)] px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <span>{t(`memory.episodes.filters.${episode.episode_type}`, { defaultValue: episode.episode_type })}</span>
          {range ? <span>{range}</span> : null}
          {episode.user_note ? <span>· {t('memory.episodes.actions.annotate')}</span> : null}
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={onTogglePin}
          aria-label={t(episode.user_pinned ? 'memory.episodes.actions.unpin' : 'memory.episodes.actions.pin')}>
          {episode.user_pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
        </Button>
        <Button variant="ghost" size="sm" onClick={onRename} aria-label={t('memory.episodes.actions.rename')}>
          <Pencil className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onAnnotate} aria-label={t('memory.episodes.actions.annotate')}>
          <MessageSquare className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="sm" onClick={onForget} aria-label={t('memory.episodes.actions.forget')}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
};

export default EpisodeRow;
```

- [ ] **Step 5: Implement MemoryEpisodesPage**

Create `frontend/src/pages/memory-pages/MemoryEpisodesPage.tsx`:

```typescript
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryApi, type L2Episode } from '@/api/modules/memory';
import EpisodeRow from '@/components/memory/episodes/EpisodeRow';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';

export const MemoryEpisodesPage = () => {
  const { t } = useTranslation('app');
  const [episodes, setEpisodes] = useState<L2Episode[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await memoryApi.listEpisodes({ status: 'active', limit: 100, offset: 0 });
      setEpisodes(payload.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const pinned = useMemo(() => episodes.filter((e) => e.user_pinned), [episodes]);
  const recent = useMemo(() => episodes.filter((e) => !e.user_pinned), [episodes]);

  const togglePin = async (ep: L2Episode) => {
    await memoryApi.annotateEpisode(ep.episode_id, { user_pinned: !ep.user_pinned });
    setEpisodes((prev) => prev.map((it) => (it.episode_id === ep.episode_id ? { ...it, user_pinned: !ep.user_pinned } : it)));
  };

  const forget = async (ep: L2Episode) => {
    await memoryApi.forgetEpisode(ep.episode_id, false);
    setEpisodes((prev) => prev.filter((it) => it.episode_id !== ep.episode_id));
  };

  const renameOrAnnotate = async (ep: L2Episode, field: 'user_label' | 'user_note') => {
    const initial = (ep[field] as string | null) ?? '';
    const next = window.prompt(t(`memory.episodes.actions.${field === 'user_label' ? 'rename' : 'annotate'}`), initial);
    if (next === null) return;
    await memoryApi.annotateEpisode(ep.episode_id, { [field]: next });
    setEpisodes((prev) => prev.map((it) => (it.episode_id === ep.episode_id ? { ...it, [field]: next } as L2Episode : it)));
  };

  return (
    <MemoryPageFrame title={t('memory.episodes.title')} description={t('memory.episodes.subtitle')}>
      {loading ? null : episodes.length === 0 ? (
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <div className="font-semibold text-[hsl(var(--memory-title))]">{t('memory.episodes.emptyTitle')}</div>
          <p className="mt-1 text-sm">{t('memory.episodes.emptyBody')}</p>
        </div>
      ) : (
        <>
          <section data-testid="episodes-pinned" className="space-y-2">
            <h2 className="text-sm font-medium text-[hsl(var(--memory-muted))]">{t('memory.episodes.pinnedSection')}</h2>
            {pinned.length === 0 ? (
              <div className="text-xs text-[hsl(var(--memory-muted))]">—</div>
            ) : (
              pinned.map((ep) => (
                <EpisodeRow
                  key={ep.episode_id}
                  episode={ep}
                  onTogglePin={() => void togglePin(ep)}
                  onRename={() => void renameOrAnnotate(ep, 'user_label')}
                  onAnnotate={() => void renameOrAnnotate(ep, 'user_note')}
                  onForget={() => void forget(ep)}
                />
              ))
            )}
          </section>

          <section data-testid="episodes-recent" className="mt-6 space-y-2">
            <h2 className="text-sm font-medium text-[hsl(var(--memory-muted))]">{t('memory.episodes.recentSection')}</h2>
            {recent.map((ep) => (
              <EpisodeRow
                key={ep.episode_id}
                episode={ep}
                onTogglePin={() => void togglePin(ep)}
                onRename={() => void renameOrAnnotate(ep, 'user_label')}
                onAnnotate={() => void renameOrAnnotate(ep, 'user_note')}
                onForget={() => void forget(ep)}
              />
            ))}
          </section>
        </>
      )}
    </MemoryPageFrame>
  );
};

export default MemoryEpisodesPage;
```

- [ ] **Step 6: Export from the page barrel**

Add to `frontend/src/pages/memory-pages/index.ts`:

```typescript
export { MemoryEpisodesPage } from './MemoryEpisodesPage';
```

- [ ] **Step 7: Run the test**

Run: `cd frontend && npm test -- memoryEpisodesPage --run`
Expected: both tests PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/memory/episodes/ \
        frontend/src/pages/memory-pages/MemoryEpisodesPage.tsx \
        frontend/src/pages/memory-pages/index.ts \
        frontend/src/api/modules/memory.ts \
        frontend/src/__tests__/memoryEpisodesPage.test.tsx
git commit -m "feat(frontend/memory): MemoryEpisodesPage with pinned + recent sections and per-row actions"
```

---

## Phase 6 — Frontend: Portrait Page

### Task 15: Portrait page and segment component

**Files:**
- Create: `frontend/src/components/memory/portrait/PortraitSegment.tsx`
- Create: `frontend/src/pages/memory-pages/MemoryPortraitPage.tsx`
- Create: `frontend/src/__tests__/memoryPortraitPage.test.tsx`
- Modify: `frontend/src/pages/memory-pages/index.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/memoryPortraitPage.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';

import i18n from '@/i18n';
import { MemoryPortraitPage } from '@/pages/memory-pages/MemoryPortraitPage';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';

vi.mock('@/api/modules/memoryPortraitSelf', () => ({
  memoryPortraitSelfApi: { get: vi.fn() },
}));

const renderPage = () =>
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>
        <MemoryPortraitPage />
      </MemoryRouter>
    </I18nextProvider>
  );

beforeEach(() => vi.clearAllMocks());

describe('MemoryPortraitPage', () => {
  it('shows cold-start text when payload is_cold_start=true', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [], is_cold_start: true, cold_start_line: '还没结论', cold_start_reason: 'no_observations',
      is_stale: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/还没结论|coldStartFallback/i)).toBeInTheDocument();
    });
  });

  it('groups observations into segments by kind', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [
        { kind: 'assertion', text: '住在杭州', basis_count: 1, basis_summary: 'projection', basis_refs: ['home_location'] },
        { kind: 'reflection', text: '好奇、专注', basis_count: 4, basis_summary: 'tom', basis_refs: ['tom-1'] },
      ],
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('住在杭州')).toBeInTheDocument();
      expect(screen.getByText('好奇、专注')).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Implement PortraitSegment**

Create `frontend/src/components/memory/portrait/PortraitSegment.tsx`:

```typescript
import type { ReactNode } from 'react';
import type { PortraitObservation } from '@/api/modules/memoryPortrait';

interface PortraitSegmentProps {
  title: string;
  observations: PortraitObservation[];
  emptyText?: string;
  renderItem?: (obs: PortraitObservation) => ReactNode;
}

export const PortraitSegment = ({ title, observations, emptyText, renderItem }: PortraitSegmentProps) => (
  <section className="rounded-2xl border border-[hsl(var(--memory-border)/0.5)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-5 py-4">
    <h2 className="text-sm font-semibold text-[hsl(var(--memory-title))]">{title}</h2>
    <div className="mt-2 space-y-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
      {observations.length === 0 ? (
        <p className="text-xs text-[hsl(var(--memory-muted))]">{emptyText ?? '—'}</p>
      ) : (
        observations.map((obs, index) => (
          <div key={`${obs.kind}-${index}`}>
            {renderItem ? renderItem(obs) : (
              <p>{obs.text}</p>
            )}
          </div>
        ))
      )}
    </div>
  </section>
);

export default PortraitSegment;
```

- [ ] **Step 3: Implement MemoryPortraitPage**

Create `frontend/src/pages/memory-pages/MemoryPortraitPage.tsx`:

```typescript
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';
import type { PortraitPayload, PortraitObservation } from '@/api/modules/memoryPortrait';
import PortraitSegment from '@/components/memory/portrait/PortraitSegment';
import MemoryPageFrame, { MEMORY_EMPTY_PANEL_CLASS } from './MemoryPageFrame';
import { DEFAULT_USER_ID } from '@/constants';

const groupByPrefix = (observations: PortraitObservation[], prefix: string) =>
  observations.filter((obs) => obs.basis_refs.some((ref) => ref.startsWith(prefix)));

import { memoryApi } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { Check, X } from 'lucide-react';

const extractAssertionId = (obs: PortraitObservation): string | null => {
  const ref = obs.basis_refs.find((r) => r.startsWith('assertion:') || /^[0-9a-f-]{20,}$/i.test(r));
  if (!ref) return null;
  return ref.startsWith('assertion:') ? ref.slice('assertion:'.length) : ref;
};

const renderReviewableObservation = (
  obs: PortraitObservation,
  onConfirm: (id: string) => void,
  onReject: (id: string) => void,
  confirmLabel: string,
  rejectLabel: string,
) => {
  const assertionId = extractAssertionId(obs);
  return (
    <div className="flex items-start justify-between gap-3">
      <p>{obs.text}</p>
      {assertionId ? (
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" aria-label={confirmLabel} onClick={() => onConfirm(assertionId)}>
            <Check className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="sm" aria-label={rejectLabel} onClick={() => onReject(assertionId)}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : null}
    </div>
  );
};

export const MemoryPortraitPage = () => {
  const { t } = useTranslation('app');
  const [payload, setPayload] = useState<PortraitPayload | null>(null);

  useEffect(() => {
    void memoryPortraitSelfApi.get(DEFAULT_USER_ID).then(setPayload).catch(() => setPayload(null));
  }, []);

  const handleConfirm = async (assertionId: string) => {
    await memoryApi.submitAssertionFeedback(assertionId, 'confirmed');
  };
  const handleReject = async (assertionId: string) => {
    await memoryApi.submitAssertionFeedback(assertionId, 'rejected');
  };
  const renderItem = (obs: PortraitObservation) => renderReviewableObservation(
    obs, handleConfirm, handleReject,
    t('memory.stories.actions.confirm'),
    t('memory.stories.actions.reject'),
  );

  if (!payload) {
    return <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')}>{null}</MemoryPageFrame>;
  }

  if (payload.is_cold_start) {
    return (
      <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')}>
        <div className={MEMORY_EMPTY_PANEL_CLASS}>
          <p className="text-sm">{payload.cold_start_line ?? t('memory.portrait.coldStartFallback')}</p>
        </div>
      </MemoryPageFrame>
    );
  }

  const identityObs = groupByPrefix(payload.observations, 'real_name').concat(
    groupByPrefix(payload.observations, 'preferred_form_of_address'),
    groupByPrefix(payload.observations, 'home_location'),
  );
  const stateObs = groupByPrefix(payload.observations, 'state:');
  const preferenceObs = groupByPrefix(payload.observations, 'preference:').concat(
    groupByPrefix(payload.observations, 'communication:'),
  );
  const impressionObs = payload.observations.filter((obs) => obs.kind === 'reflection');
  const relationshipObs = payload.observations.filter((obs) => obs.kind === 'relationship');

  return (
    <MemoryPageFrame title={t('memory.portrait.title')} description={t('memory.portrait.subtitle')}>
      <div className="space-y-3">
        <PortraitSegment title={t('memory.portrait.segments.identity')} observations={identityObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.state')} observations={stateObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.preferences')} observations={preferenceObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.relationships')} observations={relationshipObs} renderItem={renderItem} />
        <PortraitSegment title={t('memory.portrait.segments.impression')} observations={impressionObs} renderItem={renderItem} />
      </div>
    </MemoryPageFrame>
  );
};

export default MemoryPortraitPage;
```

- [ ] **Step 4: Export from the page barrel**

Add to `frontend/src/pages/memory-pages/index.ts`:

```typescript
export { MemoryPortraitPage } from './MemoryPortraitPage';
```

- [ ] **Step 5: Run the test**

Run: `cd frontend && npm test -- memoryPortraitPage --run`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/memory/portrait/ \
        frontend/src/pages/memory-pages/MemoryPortraitPage.tsx \
        frontend/src/pages/memory-pages/index.ts \
        frontend/src/__tests__/memoryPortraitPage.test.tsx
git commit -m "feat(frontend/memory): MemoryPortraitPage segmented from /portrait/self"
```

---

## Phase 7 — Frontend: Recall Page (de-tech-ified workbench)

### Task 16: MemoryRecallPage

**Files:**
- Create: `frontend/src/pages/memory-pages/MemoryRecallPage.tsx`
- Create: `frontend/src/__tests__/memoryRecallPage.test.tsx`
- Modify: `frontend/src/pages/memory-pages/index.ts`

The recall page reuses the search logic from the current `MemoryOverviewPage` but removes header stats, hides the diagnostics panel under a disclosure, and uses the user-facing mode labels from the new i18n subtree.

- [ ] **Step 1: Write the test**

Create `frontend/src/__tests__/memoryRecallPage.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';

import i18n from '@/i18n';
import { MemoryRecallPage } from '@/pages/memory-pages/MemoryRecallPage';
import { useMemory } from '@/hooks/useMemory';

vi.mock('@/hooks/useMemory');

const renderPage = () =>
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>
        <MemoryRecallPage />
      </MemoryRouter>
    </I18nextProvider>
  );

beforeEach(() => {
  vi.mocked(useMemory).mockReturnValue({
    loading: false,
    stats: { l1: { event_count: 0 }, l2: { relation_count: 0, assertion_count: 0 }, l3: { summary_count: 0 }, l4: { skill_count: 0 } },
    searchQuery: '',
    setSearchQuery: vi.fn(),
    searchResults: { l1_events: [], l2_relationships: [], l2_entity_cards: [], l3_reflections: [], l4_procedures: [], trace: {} },
    searching: false,
    handleSearch: vi.fn(),
    refreshAll: vi.fn(),
  } as unknown as ReturnType<typeof useMemory>);
});

describe('MemoryRecallPage', () => {
  it('does not show storage stats in the header', () => {
    renderPage();
    expect(screen.queryByText(/记忆条数|占用大小/)).not.toBeInTheDocument();
  });

  it('hides diagnostics panel until disclosure is toggled', async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.queryByText(/请求：|requested mode/i)).not.toBeInTheDocument();
    await user.click(screen.getByText(/调试细节|Advanced/i));
    // The disclosure content appears only after the click. Even if it's empty in this mock,
    // the panel container with data-testid should be present.
    expect(screen.getByTestId('memory-recall-diagnostics')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement the page**

Create `frontend/src/pages/memory-pages/MemoryRecallPage.tsx` by adapting `MemoryOverviewPage.tsx`:

```typescript
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { SelectField } from '@/components/config-forms/fields';
import { useMemory } from '@/hooks/useMemory';
import type { MemorySearchQueryMode } from '@/api/modules/memory';
import MemoryPageFrame, {
  MEMORY_FILTER_INPUT_CLASS,
  MEMORY_FILTER_SELECT_CLASS,
  MEMORY_EMPTY_PANEL_CLASS,
} from './MemoryPageFrame';

type RecallMode = 'auto' | 'events' | 'knowledge' | 'summaries' | 'skills' | 'state' | 'episodes';

const MODE_TO_QUERY: Record<RecallMode, MemorySearchQueryMode | undefined> = {
  auto: undefined,
  events: 'event_stream',
  knowledge: 'exact_fact',
  summaries: 'summary',
  skills: 'strategy',
  state: 'current_state',
  episodes: 'episode_recall',
};

export const MemoryRecallPage = () => {
  const { t } = useTranslation('app');
  const [mode, setMode] = useState<RecallMode>('auto');
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const {
    searchQuery, setSearchQuery, searchResults, searching, handleSearch,
  } = useMemory({ initialLoadScope: 'overview' });

  const runSearch = () => {
    const queryMode = MODE_TO_QUERY[mode];
    void handleSearch(queryMode);
  };

  const modeOptions = (['auto', 'events', 'knowledge', 'summaries', 'skills', 'state', 'episodes'] as RecallMode[])
    .map((m) => ({ value: m, label: t(`memory.recall.modes.${m}`) }));

  return (
    <MemoryPageFrame title={t('memory.recall.title')} description={t('memory.recall.subtitle')}>
      <section data-testid="memory-recall-search" className="space-y-4">
        <div className="grid gap-2 md:grid-cols-[168px_minmax(0,1fr)_auto]">
          <SelectField
            ariaLabel={t('memory.recall.title')}
            value={mode}
            onChange={(v) => setMode((v || 'auto') as RecallMode)}
            options={modeOptions}
            allowEmpty={false}
            triggerClassName={`${MEMORY_FILTER_SELECT_CLASS} justify-between shadow-none`}
            menuClassName="rounded-sm border-[hsl(var(--memory-input-border)/0.68)] bg-[hsl(var(--memory-input-bg))] shadow-[0_10px_20px_rgba(15,23,42,0.06)]"
          />
          <Input
            className={MEMORY_FILTER_INPUT_CLASS}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('memory.recall.searchPlaceholder')}
            onKeyDown={(e) => { if (e.key === 'Enter') runSearch(); }}
          />
          <Button onClick={runSearch} disabled={searching}>
            {searching ? <LoadingSpinner className="h-4 w-4" /> : <Search className="h-4 w-4" />}
          </Button>
        </div>

        {searchResults.l1_events.length === 0 && searchResults.l2_relationships.length === 0
          && (searchResults.l3_reflections?.length ?? 0) === 0 && (searchResults.l4_procedures?.length ?? 0) === 0 ? (
          <div className={MEMORY_EMPTY_PANEL_CLASS}>{t('memory.recall.noResults')}</div>
        ) : null}

        <button
          type="button"
          className="text-xs text-[hsl(var(--memory-muted))] underline-offset-2 hover:underline"
          onClick={() => setShowDiagnostics((v) => !v)}
        >
          {t('memory.recall.advancedToggle')}
        </button>
        {showDiagnostics ? (
          <div data-testid="memory-recall-diagnostics" className="rounded-xl border border-[hsl(var(--memory-border)/0.46)] bg-[hsl(var(--memory-panel-subtle)/0.36)] px-4 py-3 text-xs text-[hsl(var(--memory-muted))]">
            <pre>{JSON.stringify(searchResults.trace ?? {}, null, 2)}</pre>
          </div>
        ) : null}
      </section>
    </MemoryPageFrame>
  );
};

export default MemoryRecallPage;
```

- [ ] **Step 3: Export from the page barrel**

Add to `frontend/src/pages/memory-pages/index.ts`:

```typescript
export { MemoryRecallPage } from './MemoryRecallPage';
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && npm test -- memoryRecallPage --run`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/memory-pages/MemoryRecallPage.tsx \
        frontend/src/pages/memory-pages/index.ts \
        frontend/src/__tests__/memoryRecallPage.test.tsx
git commit -m "feat(frontend/memory): MemoryRecallPage with product-facing mode labels and disclosed diagnostics"
```

---

## Phase 8 — Frontend: Governance Page

### Task 17: MemoryGovernancePage

**Files:**
- Create: `frontend/src/pages/memory-pages/MemoryGovernancePage.tsx`
- Create: `frontend/src/__tests__/memoryGovernancePage.test.tsx`
- Modify: `frontend/src/pages/memory-pages/index.ts`

- [ ] **Step 1: Write the test**

Create `frontend/src/__tests__/memoryGovernancePage.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';

import i18n from '@/i18n';
import { MemoryGovernancePage } from '@/pages/memory-pages/MemoryGovernancePage';
import { memoryStoriesApi } from '@/api/modules/memoryStories';

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: { list: vi.fn(), review: vi.fn() },
}));

const renderPage = () =>
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>
        <MemoryGovernancePage />
      </MemoryRouter>
    </I18nextProvider>
  );

beforeEach(() => vi.clearAllMocks());

describe('MemoryGovernancePage', () => {
  it('shows pending-review count from filtered story feed', async () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      items: [
        { summary_id: 'p1', summary_type: 'insight', summary_category: 'state_change',
          title: 't', content: 'c', period_start: 0, period_end: 0, updated_at: 0,
          review_state: 'pending_confirmation', insight_key: null, insight_metadata: {}, evidence_event_count: 3 },
        { summary_id: 'p2', summary_type: 'insight', summary_category: 'state_change',
          title: 't', content: 'c', period_start: 0, period_end: 0, updated_at: 0,
          review_state: 'pending_confirmation', insight_key: null, insight_metadata: {}, evidence_event_count: 2 },
      ],
      total: 2, limit: 30, offset: 0,
    });
    renderPage();
    await waitFor(() => expect(screen.getByTestId('governance-pending-count')).toHaveTextContent('2'));
  });

  it('renders developer-view links pointing to legacy layer pages', () => {
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 });
    renderPage();
    const events = screen.getByRole('link', { name: /原始事件|Raw events/i });
    expect(events).toHaveAttribute('href', '/memory/events');
    const knowledge = screen.getByRole('link', { name: /结构化知识|Structured knowledge/i });
    expect(knowledge).toHaveAttribute('href', '/memory/knowledge');
    const skills = screen.getByRole('link', { name: /工具技能|Procedural skills/i });
    expect(skills).toHaveAttribute('href', '/memory/skills');
  });
});
```

- [ ] **Step 2: Implement the page**

Create `frontend/src/pages/memory-pages/MemoryGovernancePage.tsx`:

```typescript
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { memoryStoriesApi, type StoryItem } from '@/api/modules/memoryStories';
import { memoryApi } from '@/api/modules/memory';
import StoryCard from '@/components/memory/story/StoryCard';
import MemoryPageFrame, { MEMORY_SECTION_CARD_CLASS } from './MemoryPageFrame';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const ForgetCenter = () => {
  const [episodeId, setEpisodeId] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const handleForget = async () => {
    const id = episodeId.trim();
    if (!id) return;
    try {
      await memoryApi.forgetEpisode(id, false);
      setStatus('ok');
      setEpisodeId('');
    } catch {
      setStatus('error');
    }
  };
  return (
    <div className="mt-3 flex flex-col gap-2 md:flex-row md:items-center">
      <Input
        value={episodeId}
        onChange={(event) => setEpisodeId(event.target.value)}
        placeholder="episode_id"
        className="md:max-w-sm"
      />
      <Button onClick={() => void handleForget()} disabled={!episodeId.trim()}>遗忘章节</Button>
      {status === 'ok' ? <span className="text-xs text-emerald-600">已遗忘</span> : null}
      {status === 'error' ? <span className="text-xs text-red-500">操作失败</span> : null}
    </div>
  );
};

export const MemoryGovernancePage = () => {
  const { t } = useTranslation('app');
  const [pending, setPending] = useState<StoryItem[]>([]);

  useEffect(() => {
    void memoryStoriesApi.list({ limit: 30, offset: 0 }).then((payload) => {
      setPending(payload.items.filter((item) => item.review_state === 'pending_confirmation'));
    });
  }, []);

  const handleReview = async (story: StoryItem, state: 'confirmed' | 'rejected' | 'archived') => {
    await memoryStoriesApi.review(story.summary_id, { review_state: state });
    setPending((prev) => prev.filter((it) => it.summary_id !== story.summary_id));
  };

  return (
    <MemoryPageFrame title={t('memory.governance.title')} description={t('memory.governance.subtitle')}>
      <section className={MEMORY_SECTION_CARD_CLASS}>
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.governance.sections.pendingReview')}
          </h2>
          <span data-testid="governance-pending-count" className="text-sm text-[hsl(var(--memory-muted))]">{pending.length}</span>
        </div>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{t('memory.governance.pendingReviewBody')}</p>
        <div className="mt-3 space-y-2">
          {pending.map((story) => (
            <StoryCard
              key={story.summary_id}
              story={story}
              onConfirm={() => void handleReview(story, 'confirmed')}
              onReject={() => void handleReview(story, 'rejected')}
              onArchive={() => void handleReview(story, 'archived')}
              onOpenDetail={() => {}}
            />
          ))}
        </div>
      </section>

      <section className={`${MEMORY_SECTION_CARD_CLASS} mt-4`}>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.governance.sections.forget')}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
          {t('memory.governance.forgetBody', { defaultValue: '从这里删除某个实体、某段时间或某个章节的记忆。' })}
        </p>
        <ForgetCenter />
      </section>

      <section className={`${MEMORY_SECTION_CARD_CLASS} mt-4`}>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.governance.sections.privacy')}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">
          {t('memory.governance.privacyBody', { defaultValue: '查看每个来源当前的隐私范围。修改在「设置」里完成。' })}
        </p>
      </section>

      <section className={`${MEMORY_SECTION_CARD_CLASS} mt-4`}>
        <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
          {t('memory.governance.sections.developer')}
        </h2>
        <p className="mt-1 text-sm text-[hsl(var(--memory-body))]">{t('memory.governance.developerBody')}</p>
        <ul className="mt-3 grid gap-2 md:grid-cols-2">
          <li>
            <Link to="/memory/events" className="block rounded-xl border border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-4 py-3 text-sm">
              {t('memory.nav.dev.events')}
            </Link>
          </li>
          <li>
            <Link to="/memory/knowledge" className="block rounded-xl border border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-4 py-3 text-sm">
              {t('memory.nav.dev.knowledge')}
            </Link>
          </li>
          <li>
            <Link to="/memory/skills" className="block rounded-xl border border-[hsl(var(--memory-border)/0.55)] bg-[hsl(var(--memory-panel-elevated)/0.65)] px-4 py-3 text-sm">
              {t('memory.nav.dev.skills')}
            </Link>
          </li>
        </ul>
      </section>
    </MemoryPageFrame>
  );
};

export default MemoryGovernancePage;
```

- [ ] **Step 3: Export from the page barrel**

Add to `frontend/src/pages/memory-pages/index.ts`:

```typescript
export { MemoryGovernancePage } from './MemoryGovernancePage';
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && npm test -- memoryGovernancePage --run`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/memory-pages/MemoryGovernancePage.tsx \
        frontend/src/pages/memory-pages/index.ts \
        frontend/src/__tests__/memoryGovernancePage.test.tsx
git commit -m "feat(frontend/memory): MemoryGovernancePage with pending-review queue and developer-view links"
```

---

## Phase 9 — Cleanup

### Task 18: Delete replaced pages and stale tests

**Files:**
- Delete: `frontend/src/pages/memory-pages/MemoryOverviewPage.tsx`
- Delete: `frontend/src/pages/memory-pages/MemoryWorkbenchPage.tsx`
- Delete: `frontend/src/pages/memory-pages/MemoryReflectionPage.tsx`
- Delete: `frontend/src/__tests__/useMemoryInitialLoadScope.test.tsx`
- Modify: `frontend/src/pages/memory-pages/index.ts`
- Modify: `frontend/src/__tests__/appShellRouting.test.tsx`

- [ ] **Step 1: Confirm there are no remaining importers of the deleted pages**

Run: `grep -rn "MemoryOverviewPage\|MemoryWorkbenchPage\|MemoryReflectionPage" frontend/src --include="*.tsx" --include="*.ts" | grep -v __tests__`
Expected: only references remaining should be inside the index barrel and the deleted files themselves.

If any importer remains in non-test code, fix it before deleting (replace with the corresponding new page).

- [ ] **Step 2: Remove exports from the barrel**

In `frontend/src/pages/memory-pages/index.ts`, remove:

```typescript
export { MemoryOverviewPage } from './MemoryOverviewPage';
export { MemoryWorkbenchPage } from './MemoryWorkbenchPage';
export { MemoryReflectionPage } from './MemoryReflectionPage';
```

If `MemoryEventsPage`, `MemoryKnowledgePage`, and `MemorySkillsPage` exports are still present, keep them — they back the `/memory/events`, `/memory/knowledge`, `/memory/skills` developer-view routes.

- [ ] **Step 3: Delete the page files**

Run:

```bash
rm frontend/src/pages/memory-pages/MemoryOverviewPage.tsx
rm frontend/src/pages/memory-pages/MemoryWorkbenchPage.tsx
rm frontend/src/pages/memory-pages/MemoryReflectionPage.tsx
```

- [ ] **Step 4: Delete the legacy hook test**

The `useMemoryInitialLoadScope.test.tsx` test pinned the old overview-page hook behavior. The behavior is replaced by per-page tests added in Phases 4–8.

Run: `rm frontend/src/__tests__/useMemoryInitialLoadScope.test.tsx`

- [ ] **Step 5: Update appShellRouting test**

In `frontend/src/__tests__/appShellRouting.test.tsx`, find any reference to `MemoryOverviewPage`, `MemoryWorkbenchPage`, or `MemoryReflectionPage` and replace with the corresponding new page (`MemoryStoryPage`, `MemoryRecallPage`, etc.).

Run `grep -n "Memory" frontend/src/__tests__/appShellRouting.test.tsx` to see what to change, then update the route-assertion mocks. Each old mock like:

```typescript
MemoryOverviewPage: () => <div data-testid="memory-overview-page">memory-overview-page</div>,
```

should become a corresponding new mock such as:

```typescript
MemoryStoryPage: () => <div data-testid="memory-story-page">memory-story-page</div>,
```

Add equivalent mocks for `MemoryEpisodesPage`, `MemoryPortraitPage`, `MemoryRecallPage`, `MemoryGovernancePage`.

- [ ] **Step 6: Run the test**

Run: `cd frontend && npm test -- appShellRouting --run`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src/pages/memory-pages/ frontend/src/__tests__/appShellRouting.test.tsx
git rm frontend/src/__tests__/useMemoryInitialLoadScope.test.tsx
git commit -m "chore(frontend/memory): remove replaced overview/workbench/reflection pages and stale tests"
```

### Task 19: Final verification

**Files:** all

- [ ] **Step 1: Type-check the frontend**

Run: `cd frontend && npm run typecheck`
Expected: 0 errors.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm test --run`
Expected: all tests PASS. If any unrelated test breaks because it referenced removed memory exports, fix the test to use the new exports or remove the assertion.

- [ ] **Step 3: Run the backend test suite**

Run: `cd backend && pytest tests/api/test_memory_stories_routes.py tests/api/test_memory_portrait_self_routes.py tests/memory/l3/test_review_operations.py tests/api/test_memory_portrait_routes.py -v`
Expected: all tests PASS.

- [ ] **Step 4: Smoke-test the dev server**

Use the existing dev-server workflow described in the repository's CONTRIBUTING.md (or `npm run dev` from `frontend/`). Navigate to:

- `/memory/stories` — should land here from sidebar
- `/memory/episodes`
- `/memory/portrait`
- `/memory/recall`
- `/memory/governance`
- `/memory/overview` (legacy) — should redirect to `/memory/stories`
- `/memory/workbench` (legacy) — should redirect to `/memory/recall`
- `/memory/reflection` (legacy) — should redirect to `/memory/stories`

Confirm each loads without console errors. For pages with no production data, the empty/cold-start text from the i18n bundle should render.

- [ ] **Step 5: Final commit if any small fixes were needed**

If type-check / tests / smoke-test surfaced trivial fixes, commit them:

```bash
git add -A
git commit -m "chore(memory): final type/lint/test fixes after taxonomy migration"
```

---

## Out of Scope (deferred per spec)

- Cross-insight narrative arc table or schema additions.
- Per-entity biography view (person/place/topic 卷宗).
- Underlying memory schema or retrieval pipeline changes.
- Timeline page redesign.

## Spec Coverage Map

| Spec section | Task(s) |
|---|---|
| Sidebar five-item taxonomy | 7, 8, 10 |
| Routes & redirects | 9, 18 |
| Story view (cards, ordering, drill-down, empty state) | 1, 3, 11–13 |
| Episodes view (pin, annotate, forget) | 14 |
| Portrait view (segments, cold-start, per-observation review) | 4, 15 |
| Recall view (renamed modes, hidden diagnostics, no stats) | 16 |
| Governance view (pending queue, forget center, privacy scope, developer subtree) | 17 |
| Self-portrait backend extension | 4 |
| i18n keys | 7 |
| Test updates | 10, 13, 14, 15, 16, 17, 18 |
| Cleanup of deprecated pages | 18 |
| Final verification | 19 |
