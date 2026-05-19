# Timeline Immersive Redesign — Plan 3: Frontend Rewrite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current dashboard-style `/timeline` page with the immersive "memory time-capsule" experience defined in the spec. Backend additions are limited to surfacing the Plan-1/2 fields through the existing viewport endpoint plus a new photo-serving route. Frontend is a near-complete rewrite of `frontend/src/components/timeline/` and `frontend/src/pages/Timeline.tsx`.

**Architecture:** The new page is composed of (a) a left sidebar with a **MoodCalendar** (consumes `/timeline/mood-calendar`) + a "**值得回来的**" list (consumes `/timeline/standout`), and (b) a main pane that is either a **PeriodCard** (month/week/day = immersive narrative) or a **HourDetail** flat list (hour = detective mode). The PeriodCard composes Hero (photo or atmospheric gradient) + StateBand + ThemesRow + Slice list. Slices acquire ♡ (add to "值得回来的") + ⋯ ("不算这天的样子") gestures via the existing `annotateEpisode` / `forgetEpisode` APIs. Default landing scale changes from `month` → `day`. `TimelineContextDrawer` and the in-page calibration handlers are deleted entirely.

**Tech Stack:** React 18.2 (strict TS), Tailwind + shadcn-ui + Radix, Zustand, react-i18next, Vitest 2.1.5 + jsdom + @testing-library/react. Backend gap additions: Python FastAPI (existing timeline router), Rust gateway proxy entry, no new Alembic migrations.

---

## Reference docs

- Spec: [docs/superpowers/specs/2026-05-19-timeline-immersive-redesign-design.md](../specs/2026-05-19-timeline-immersive-redesign-design.md)
- Plan 1 (foundations): [2026-05-19-timeline-immersive-plan-1-backend-foundations.md](./2026-05-19-timeline-immersive-plan-1-backend-foundations.md)
- Plan 2 (generation): [2026-05-19-timeline-immersive-plan-2-generation-pipeline.md](./2026-05-19-timeline-immersive-plan-2-generation-pipeline.md)
- Existing page to replace: [frontend/src/pages/Timeline.tsx](../../../frontend/src/pages/Timeline.tsx)
- Existing API client: [frontend/src/api/modules/timeline.ts](../../../frontend/src/api/modules/timeline.ts)
- Existing components to delete/refactor: [frontend/src/components/timeline/](../../../frontend/src/components/timeline/)
- Reference for new gateway route: [crates/magi-gateway/src/api/messages/attachments.rs](../../../crates/magi-gateway/src/api/messages/attachments.rs) (handler pattern, not the table)

## What's NOT in Plan 3

- **On-demand diary generation endpoint**. If a user navigates to a historical period that has no L3 `essence_prose` yet, the UI shows existing data (cluster `summary` / `label`) without generating new prose synchronously. Adding a `POST /api/timeline/diary/generate` is a Plan 4 candidate.
- **English i18n keys**. Plan 3 ships Chinese (zh-CN) keys only; English (`en/app.json`) keeps showing the keys verbatim. A bilingualization pass can come later.
- **HEIC → JPEG conversion**. Photos served via the new asset route preserve their source MIME type. Safari users see HEIC inline; Chrome users see a broken-image icon for HEIC. JPEG conversion is a Plan 4 concern.
- **Tauri title-bar integration**. The recent title-bar work (per recent commits) stays unchanged.
- **Mobile / responsive layout**. Plan 3 targets the desktop window sizes Magi ships in. Mobile-grade responsiveness is deferred.
- **Per-persona narrative voice variants**. The diary essence stays neutral 2nd-person (the spec's v1 voice).

## File structure (created / modified / deleted)

**Created:**
- `frontend/src/components/timeline/immersive/Hero.tsx`
- `frontend/src/components/timeline/immersive/StateBand.tsx`
- `frontend/src/components/timeline/immersive/ThemesRow.tsx`
- `frontend/src/components/timeline/immersive/Slice.tsx`
- `frontend/src/components/timeline/immersive/PeriodCard.tsx`
- `frontend/src/components/timeline/immersive/HourDetail.tsx`
- `frontend/src/components/timeline/immersive/PeriodCardEmpty.tsx`
- `frontend/src/components/timeline/immersive/sidebar/MoodCalendar.tsx`
- `frontend/src/components/timeline/immersive/sidebar/StandoutList.tsx`
- `frontend/src/components/timeline/immersive/sidebar/TimelineSidebar.tsx`
- `frontend/src/components/timeline/immersive/Toolbar.tsx`
- `frontend/src/utils/timelineAssetUrl.ts` — resolves `photo-library://...` → fetchable URL
- `frontend/src/__tests__/timeline/Hero.test.tsx`
- `frontend/src/__tests__/timeline/Slice.test.tsx`
- `frontend/src/__tests__/timeline/PeriodCard.test.tsx`
- `frontend/src/__tests__/timeline/HourDetail.test.tsx`
- `frontend/src/__tests__/timeline/MoodCalendar.test.tsx`
- `frontend/src/__tests__/timeline/StandoutList.test.tsx`
- `frontend/src/__tests__/timeline/TimelinePageImmersive.test.tsx`
- `backend/tests/api/test_timeline_asset_route.py`

**Modified:**
- `backend/src/magi/timeline/viewport_builder.py` (or service.py) — surface `essence_prose` on overview + `slice_narrative` / `slice_sensory_detail` / `representative_asset_ref` on clusters
- `backend/src/magi/timeline/service.py` — extend `get_viewport` typed dict (if it has one)
- `backend/src/magi/api/routers/timeline.py` — add `GET /asset/{ref:path}` Python handler
- `backend/src/magi/api/routes.py` — register `/asset/{ref:path}` as public
- `frontend/src/api/modules/timeline.ts` — extend `TimelineClusterBlock` + `TimelineOverview`; add `getStandout`, `getMoodCalendar`, `getAssetUrl` helpers
- `frontend/src/pages/Timeline.tsx` — wholesale rewrite, removing drawer + calibration handlers + month default
- `frontend/src/i18n/locales/zh-CN/app.json` — add `timeline.immersive.*` keys

**Deleted:**
- `frontend/src/components/timeline/TimelineContextDrawer.tsx`
- `frontend/src/components/timeline/TimelineToolbar.tsx` (replaced by smaller `immersive/Toolbar.tsx`)
- `frontend/src/components/timeline/MonthOverviewLane.tsx`
- `frontend/src/components/timeline/DayClusterLane.tsx`
- `frontend/src/components/timeline/HourDetailLane.tsx`
- `frontend/src/components/timeline/StateBandOverlay.tsx`
- `frontend/src/components/timeline/HighlightCards.tsx`
- `frontend/src/components/timeline/TimelineViewport.tsx`
- `frontend/src/__tests__/timelinePage.test.tsx` (replaced by `TimelinePageImmersive.test.tsx`)

---

## Task 1: Backend — surface Plan-1/2 fields through the viewport response

**Files:**
- Modify: `backend/src/magi/timeline/viewport_builder.py` (or wherever `TimelineClusterBlock` is constructed)
- Modify: `backend/src/magi/timeline/service.py` if it shapes the overview separately
- Test: extend `backend/tests/api/test_timeline_viewport.py` (or create one if missing)

The viewport response currently does not surface the new fields populated by Plan 2. We need: `overview.essence_prose` (period-level, from L3 by `insight_key="diary-day-YYYY-MM-DD"`) and per-cluster `slice_narrative`, `slice_sensory_detail`, `representative_asset_ref` (from L2 episode).

#### Step 1: Inspect the cluster-build path

```bash
cd /Users/asuka/code/magi/backend && grep -n "TimelineClusterBlock\|episode_id\|build_cluster" src/magi/timeline/viewport_builder.py src/magi/timeline/cluster_builder.py 2>/dev/null | head -20
```

Locate where a cluster dict is assembled from an L2 episode row. This is where the new fields get pulled through.

#### Step 2: Write the failing test

If `backend/tests/api/test_timeline_viewport.py` doesn't exist yet, create it. Add (or append) the following test:

```python
"""Tests that the viewport surfaces Plan-1/2 immersive fields."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_viewport_cluster_surfaces_slice_narrative_and_asset_ref(
    unified_memory_for_tests, l2_store_for_tests,
):
    from magi.timeline.service import TimelineService

    # Seed an active episode with all the new immersive fields populated
    await l2_store_for_tests.create_episode(
        episode_id="ep-imm", time_start=100.0, time_end=200.0,
    )
    await l2_store_for_tests.update_episode(
        episode_id="ep-imm",
        status="active",
        label="afternoon coding",
        slice_narrative="下午你读了 timeline-domain 的架构文档。",
        slice_sensory_detail="窗外光线很柔。",
        representative_asset_ref="photo-library://2026-05-17/IMG.HEIC",
    )

    service = TimelineService(unified_memory_for_tests)
    viewport = await service.get_viewport(
        scale="day", start=0.0, end=500.0,
        query=None, timezone=None, locale="zh", focus="self",
    )

    clusters = viewport.get("clusters") or []
    assert clusters, "expected at least one cluster from the active episode"
    cluster = next((c for c in clusters if c.get("episode_id") == "ep-imm"), None)
    assert cluster is not None
    assert cluster.get("slice_narrative") == "下午你读了 timeline-domain 的架构文档。"
    assert cluster.get("slice_sensory_detail") == "窗外光线很柔。"
    assert cluster.get("representative_asset_ref") == "photo-library://2026-05-17/IMG.HEIC"


@pytest.mark.asyncio
async def test_viewport_overview_surfaces_essence_prose_when_l3_exists(
    unified_memory_for_tests, l2_store_for_tests, tmp_path,
):
    from magi.memory.l3.summary_store import L3SummaryStore
    from magi.memory.l3.models import L3Candidate
    from magi.timeline.service import TimelineService
    from datetime import datetime, timezone

    # Seed an L3 summary with the matching insight_key for the day window
    # Day in question: 2024-05-20 UTC → insight_key = "diary-day-2024-05-20"
    l3_store = L3SummaryStore(db_path=str(unified_memory_for_tests.memory_db_path))
    await l3_store.initialize()
    await l3_store.upsert_candidate(
        candidate=L3Candidate(
            summary_type="temporal",
            summary_category="day",
            content="essence body",
            source_event_ids=[],
            insight_key="diary-day-2024-05-20",
        ),
        summary_overrides={
            "narrative_style": "diary_2p",
            "essence_prose": "周日。你大部分时间在 localhost 之间游走。",
        },
    )

    # Day window: 2024-05-20 00:00 UTC – 2024-05-21 00:00 UTC
    day_start = datetime(2024, 5, 20, tzinfo=timezone.utc).timestamp()
    day_end = day_start + 86400.0

    service = TimelineService(unified_memory_for_tests)
    viewport = await service.get_viewport(
        scale="day", start=day_start, end=day_end,
        query=None, timezone=None, locale="zh", focus="self",
    )

    overview = viewport.get("overview") or {}
    assert overview.get("essence_prose") == "周日。你大部分时间在 localhost 之间游走。"
```

#### Step 3: Run, expect failure

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/api/test_timeline_viewport.py -v
```

Expected: clusters missing the new fields, overview missing `essence_prose`.

#### Step 4: Extend cluster projection

Locate the cluster-projection code (from Step 1). It currently maps L2 episode rows → cluster dicts. Add three keys to the projection:

```python
        "slice_narrative": str(episode.get("slice_narrative") or ""),
        "slice_sensory_detail": str(episode.get("slice_sensory_detail") or ""),
        "representative_asset_ref": str(episode.get("representative_asset_ref") or ""),
```

(Place them next to `user_label` / `user_note` / `user_pinned` so all per-episode fields are grouped.)

#### Step 5: Surface essence_prose on overview

In whichever module builds the `overview` dict for the viewport response, add a lookup against L3 by `insight_key`:

```python
        # Find the matching L3 diary essence for this period, if any.
        from datetime import datetime, timezone

        period_start_date = datetime.fromtimestamp(period_start, tz=timezone.utc).date().isoformat()
        insight_key = f"diary-{scale}-{period_start_date}"

        l3_store = getattr(self._unified_memory, "l3", None)  # confirm attribute name
        essence_prose = ""
        if l3_store is not None:
            summary = await l3_store._find_summary_by_insight_key(insight_key=insight_key)
            if summary and summary.get("narrative_style") == "diary_2p":
                essence_prose = str(summary.get("essence_prose") or "")

        overview["essence_prose"] = essence_prose
```

> **CRITICAL:** verify the L3 store attribute name on `unified_memory`. Look at `backend/src/magi/memory/unified_store.py`. If it's not `.l3`, use the actual name. If L3 store isn't exposed yet, fall back to constructing it from `unified_memory.memory_db_path` like the `/mood-calendar` endpoint already does.

The `insight_key` format must match what Plan 2's `DiaryNarrativeSchedulerContrib` writes — confirm by grepping `diary-day-` in `backend/src/magi/timeline/narrative/scheduler_contrib.py`.

#### Step 6: Run, expect pass

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/api/test_timeline_viewport.py -v
```

Expected: both tests pass.

#### Step 7: Commit

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/ backend/tests/api/test_timeline_viewport.py && git commit -m "feat(timeline/viewport): surface essence_prose + slice narrative + representative_asset_ref"
```

---

## Task 2: Backend — `GET /api/timeline/asset/{ref:path}` photo-serving endpoint

**Files:**
- Modify: `backend/src/magi/api/routers/timeline.py`
- Modify: `backend/src/magi/api/routes.py` — register `/asset/{ref:path}` as public
- Test: `backend/tests/api/test_timeline_asset_route.py`

Resolves `photo-library://YYYY-MM-DD/FILENAME` (and future schemes) into a local file path via the photo-library plugin's reader, streams the binary back with the appropriate `Content-Type`. Python-served for simplicity; bytes flow through IPC. Plan 4 can optimize.

#### Step 1: Write the failing test

Create `backend/tests/api/test_timeline_asset_route.py`:

```python
"""Tests for GET /api/timeline/asset/{ref:path}."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_asset_endpoint_returns_404_for_unknown_scheme(unified_memory_for_tests):
    from magi.timeline.service import TimelineService

    service = TimelineService(unified_memory_for_tests)
    result = await service.serve_asset(asset_ref="unknown://nope.jpg")
    assert result is None  # → 404 at the route


@pytest.mark.asyncio
async def test_asset_endpoint_returns_404_when_file_missing(unified_memory_for_tests):
    from magi.timeline.service import TimelineService

    service = TimelineService(unified_memory_for_tests)
    # photo-library scheme but the file doesn't exist on disk
    result = await service.serve_asset(asset_ref="photo-library://2099-01-01/never.HEIC")
    assert result is None


@pytest.mark.asyncio
async def test_asset_endpoint_streams_existing_file(unified_memory_for_tests, tmp_path, monkeypatch):
    """When the photo-library plugin's reader resolves the ref to an existing
    file path, the route returns the bytes with the right Content-Type."""
    from magi.timeline.service import TimelineService

    fake_file = tmp_path / "IMG.heic"
    fake_file.write_bytes(b"\x00\x01\x02\x03")  # 4 bytes of "image content"

    # Patch the asset_ref → path resolver to return our fake file
    async def fake_resolver(asset_ref: str):
        if asset_ref == "photo-library://2026-05-17/IMG.HEIC":
            return str(fake_file), "image/heic"
        return None, None

    monkeypatch.setattr(
        "magi.timeline.service._resolve_photo_library_asset",
        fake_resolver,
        raising=False,
    )

    service = TimelineService(unified_memory_for_tests)
    result = await service.serve_asset(asset_ref="photo-library://2026-05-17/IMG.HEIC")

    assert result is not None
    body_bytes, content_type = result
    assert body_bytes == b"\x00\x01\x02\x03"
    assert content_type == "image/heic"
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/api/test_timeline_asset_route.py -v
```

#### Step 3: Implement `serve_asset` on `TimelineService`

In `backend/src/magi/timeline/service.py`, add (next to `list_standout` and `list_mood_calendar`):

```python
    async def serve_asset(self, *, asset_ref: str) -> Optional[tuple[bytes, str]]:
        """Resolve an asset_ref and read its bytes from disk.

        Returns (bytes, content_type) on success, None when the ref is
        unrecognized or the file is missing. The route turns None into 404.
        """
        if not asset_ref:
            return None

        scheme, _, rest = asset_ref.partition("://")
        if scheme == "photo-library":
            file_path, content_type = await _resolve_photo_library_asset(asset_ref)
            if not file_path:
                return None
            try:
                with open(file_path, "rb") as fh:
                    data = fh.read()
            except OSError:
                return None
            return data, content_type or "application/octet-stream"

        # Future schemes (chat-attachment://, screen-capture://) plug in here
        return None
```

Also at module level in `service.py`, add the resolver (a thin stub that delegates to the photo-library plugin's `reader`):

```python
async def _resolve_photo_library_asset(asset_ref: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve a photo-library:// ref to (file_path, content_type).

    Plan 3 ships a minimal resolver that asks the running photo-library
    plugin (via the host's plugin manager) for the path. If the plugin is
    not loaded or doesn't recognize the ref, returns (None, None).

    The real implementation lives in the photo-library plugin's reader;
    this just hands off the request.
    """
    try:
        # Imported lazily so unit tests can monkeypatch the module-level symbol.
        from magi.plugins.runtime import get_plugin_runtime  # adjust to actual import path
        runtime = get_plugin_runtime()
        plugin = runtime.get_plugin("photo-library") if runtime else None
        if plugin is None:
            return None, None
        reader = getattr(plugin, "reader", None) or getattr(plugin, "_reader", None)
        if reader is None:
            return None, None
        resolved = await reader.resolve_asset_ref(asset_ref)
        if not resolved:
            return None, None
        return str(resolved.get("file_path") or ""), str(resolved.get("content_type") or "application/octet-stream")
    except Exception:
        return None, None
```

> **IMPLEMENTER ADAPTATION NOTE:** the exact import path for the plugin runtime accessor + the reader's API (`resolve_asset_ref` vs `lookup` vs whatever the plugin actually exposes) depends on what the photo-library plugin's `reader.py` declares. Inspect `target/release/sidecar-dist/_internal/plugins/photo-library/reader.py` to confirm. If the reader doesn't expose `resolve_asset_ref`, write a thin wrapper that calls whatever method DOES exist (e.g., parse the ref into date+filename, hand to `reader.get_photo_by_date_and_filename`).
>
> If the plugin runtime accessor doesn't exist as a free function, find the actual way to get a plugin instance (probably via `unified_memory` or a `plugin_registry` injected into `TimelineService`). If `TimelineService.__init__` doesn't have access, accept this as a Plan-3 limitation: ship the route with a `# TODO` returning 404 for now, and document for Plan 4 that the photo-library plugin needs a public host-callable `resolve` API. Don't go deeper than 1 import-path investigation.

#### Step 4: Add the route handler

In `backend/src/magi/api/routers/timeline.py`, add:

```python
from fastapi import Response


@timeline_router.get("/asset/{asset_ref:path}")
async def get_timeline_asset(asset_ref: str):
    service = get_timeline_service()
    result = await service.serve_asset(asset_ref=asset_ref)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    body, content_type = result
    return Response(content=body, media_type=content_type)
```

#### Step 5: Register the route as public

In `backend/src/magi/api/routes.py`, extend the `timeline` block in `_PUBLIC_ROUTE_METHODS`. Currently:

```python
    "timeline": {
        "/viewport": {"GET"},
        "/context/{anchor_id}": {"GET"},
        "/standout": {"GET"},
        "/mood-calendar": {"GET"},
    },
```

Add `/asset/{asset_ref}`:

```python
    "timeline": {
        "/viewport": {"GET"},
        "/context/{anchor_id}": {"GET"},
        "/standout": {"GET"},
        "/mood-calendar": {"GET"},
        "/asset/{asset_ref}": {"GET"},
    },
```

> Note: FastAPI's `{ref:path}` converter accepts slashes in the URL parameter. The `_PUBLIC_ROUTE_METHODS` pattern should not include the `:path` converter (it's just the routing key).

#### Step 6: Run, expect pass

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/api/test_timeline_asset_route.py -v
```

Expected: 3 passed.

#### Step 7: Commit

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/service.py backend/src/magi/api/routers/timeline.py backend/src/magi/api/routes.py backend/tests/api/test_timeline_asset_route.py && git commit -m "feat(api/timeline): GET /asset/{ref:path} serves photo-library assets"
```

---

## Task 3: Frontend — extend `timelineApi` types + add new helpers

**Files:**
- Modify: `frontend/src/api/modules/timeline.ts`
- Create: `frontend/src/utils/timelineAssetUrl.ts`

Add the new fields the backend now surfaces, plus client functions for the Plan-1 endpoints `/standout` and `/mood-calendar` (no tests yet for these — they're thin wrappers; tested via component tests later).

#### Step 1: Inspect current api client shape

```bash
sed -n '1,50p' /Users/asuka/code/magi/frontend/src/api/modules/timeline.ts
```

Note the existing `apiClient` import / API base pattern.

#### Step 2: Extend the file

Find the `TimelineClusterBlock` interface (around line 26) and add the new optional fields:

```typescript
export interface TimelineClusterBlock {
  // ... existing fields unchanged ...

  // Plan 1+2 immersive fields, surfaced by Plan 3 backend Task 1
  slice_narrative?: string;
  slice_sensory_detail?: string;
  representative_asset_ref?: string;
}
```

Find the `TimelineViewportResponse` interface and locate `overview` — add to the overview's nested type:

```typescript
export interface TimelineOverview {
  title: string;
  summary: string;
  key_takeaways: string[];
  confidence?: number;
  essence_prose?: string;  // NEW — Plan 2 generated 2nd-person diary essence
}
```

At the bottom of the file, add the new API functions:

```typescript
export interface TimelineStandoutItem {
  episode_id: string;
  scale: string;
  start: number;
  end: number;
  title: string;
  date: string;
  source: "user" | "magi";
  score: number;
}

export interface TimelineStandoutResponse {
  month: string | null;
  items: TimelineStandoutItem[];
}

export interface TimelineMoodCalendarDay {
  date: string;
  dominant_valence: string;
  volatility: number;
  event_count: number;
  sparkline: number[];
}

export interface TimelineMoodCalendarResponse {
  month: string;
  days: TimelineMoodCalendarDay[];
}

export const timelineApi = {
  // ... existing functions unchanged ...

  async getStandout(month?: string, limit = 50): Promise<TimelineStandoutResponse> {
    const params = new URLSearchParams();
    if (month) params.set("month", month);
    params.set("limit", String(limit));
    const response = await apiClient.get(`/api/timeline/standout?${params.toString()}`);
    return response.data;
  },

  async getMoodCalendar(month: string): Promise<TimelineMoodCalendarResponse> {
    const params = new URLSearchParams({ month });
    const response = await apiClient.get(`/api/timeline/mood-calendar?${params.toString()}`);
    return response.data;
  },
};
```

#### Step 3: Create the asset URL helper

Create `frontend/src/utils/timelineAssetUrl.ts`:

```typescript
/**
 * Resolve a timeline asset_ref (e.g. "photo-library://2026-05-17/IMG.HEIC")
 * into a URL the browser can <img src> from.
 *
 * Returns null for empty or unrecognized refs so callers can fall back to
 * the atmospheric-gradient placeholder.
 */
export function resolveTimelineAssetUrl(assetRef: string | null | undefined): string | null {
  if (!assetRef) return null;
  const trimmed = assetRef.trim();
  if (!trimmed) return null;

  // The backend gateway accepts any asset scheme; we let it 404 for unknown ones.
  return `/api/timeline/asset/${encodeURIComponent(trimmed)}`;
}
```

#### Step 4: Smoke-check the imports

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run --reporter=verbose src/api/modules/timeline.ts 2>&1 | tail -3
```

Expected: no test files collected for the module itself, but no TS errors when other tests import it. If TS strict complains about the new fields, fix the type definitions.

```bash
cd /Users/asuka/code/magi/frontend && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no new errors caused by Plan 3's additions. Pre-existing errors elsewhere are not your concern.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/api/modules/timeline.ts frontend/src/utils/timelineAssetUrl.ts && git commit -m "feat(frontend/timeline): extend api types for immersive fields + asset URL helper"
```

---

## Task 4: Frontend — `Hero` component

**Files:**
- Create: `frontend/src/components/timeline/immersive/Hero.tsx`
- Test: `frontend/src/__tests__/timeline/Hero.test.tsx`

The hero is the full-bleed visual at the top of a PeriodCard. Photo case: full-bleed `<img>` with dark-bottom gradient overlay so white text is legible. Fallback: a warm gradient generated from the day's dominant valence (see `StateBand` later — for the hero, we just take a single dominant color hint).

Props:
- `dateLabel: string` — formatted like "2026 · 5 · 17 · 周日"
- `essenceProse: string` — 1–3 sentence 2nd-person diary essence (may be empty)
- `placeLine?: string` — optional "家 · 楼下咖啡店"
- `photoUrl: string | null` — resolved from `representative_asset_ref`; null means use gradient
- `fallbackTone?: "warm" | "cool" | "neutral" | "bright" | "tense"` — drives gradient color when photoUrl is null

Visual: 280px tall on day scale (component is presentational only; the page decides height).

#### Step 1: Write the failing test

Create `frontend/src/__tests__/timeline/Hero.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { Hero } from "@/components/timeline/immersive/Hero";

describe("Hero", () => {
  it("renders date label, essence prose, and place line", () => {
    render(
      <Hero
        dateLabel="2026 · 5 · 17 · 周日"
        essenceProse="周日。你大部分时间在 localhost 之间游走。"
        placeLine="家 · 楼下咖啡店"
        photoUrl={null}
        fallbackTone="cool"
      />
    );

    expect(screen.getByText("2026 · 5 · 17 · 周日")).toBeInTheDocument();
    expect(
      screen.getByText("周日。你大部分时间在 localhost 之间游走。")
    ).toBeInTheDocument();
    expect(screen.getByText(/家.*楼下咖啡店/)).toBeInTheDocument();
  });

  it("renders an <img> when photoUrl is provided", () => {
    render(
      <Hero
        dateLabel="2026 · 5 · 17"
        essenceProse=""
        photoUrl="/api/timeline/asset/photo-library%3A%2F%2F2026-05-17%2FIMG.HEIC"
        fallbackTone="warm"
      />
    );

    const img = screen.getByRole("img", { hidden: true });
    expect(img).toHaveAttribute(
      "src",
      "/api/timeline/asset/photo-library%3A%2F%2F2026-05-17%2FIMG.HEIC"
    );
  });

  it("omits the place line element when not provided", () => {
    render(
      <Hero
        dateLabel="2026 · 5 · 17"
        essenceProse="x"
        photoUrl={null}
        fallbackTone="neutral"
      />
    );

    expect(screen.queryByText(/家/)).not.toBeInTheDocument();
  });

  it("applies a different gradient tone class for each fallbackTone", () => {
    const { container, rerender } = render(
      <Hero
        dateLabel="d"
        essenceProse="e"
        photoUrl={null}
        fallbackTone="warm"
      />
    );
    const warmHero = container.firstElementChild!;
    const warmClass = warmHero.className;

    rerender(
      <Hero
        dateLabel="d"
        essenceProse="e"
        photoUrl={null}
        fallbackTone="tense"
      />
    );
    const tenseHero = container.firstElementChild!;
    expect(tenseHero.className).not.toBe(warmClass);
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/Hero.test.tsx
```

Expected: `Failed to load url @/components/timeline/immersive/Hero` (module missing).

#### Step 3: Create the component

Create `frontend/src/components/timeline/immersive/Hero.tsx`:

```typescript
import React from "react";

import { cn } from "@/lib/utils";

export type HeroFallbackTone =
  | "warm"
  | "cool"
  | "neutral"
  | "bright"
  | "tense";

interface HeroProps {
  dateLabel: string;
  essenceProse: string;
  placeLine?: string;
  photoUrl: string | null;
  fallbackTone?: HeroFallbackTone;
  className?: string;
}

const TONE_GRADIENTS: Record<HeroFallbackTone, string> = {
  warm: "bg-gradient-to-br from-[#d4b886] via-[#c9a878] to-[#8a7a5a]",
  bright: "bg-gradient-to-br from-[#e8d3a0] via-[#d4b886] to-[#a89070]",
  neutral: "bg-gradient-to-br from-[#c2bba8] via-[#a8a08a] to-[#8a8275]",
  cool: "bg-gradient-to-br from-[#a8b4c2] via-[#7a8898] to-[#5a6878]",
  tense: "bg-gradient-to-br from-[#c2a098] via-[#b87a78] to-[#8a5050]",
};

export const Hero: React.FC<HeroProps> = ({
  dateLabel,
  essenceProse,
  placeLine,
  photoUrl,
  fallbackTone = "neutral",
  className,
}) => {
  const hasPhoto = Boolean(photoUrl);

  return (
    <div
      className={cn(
        "relative h-[280px] overflow-hidden",
        !hasPhoto && TONE_GRADIENTS[fallbackTone],
        className
      )}
    >
      {hasPhoto && photoUrl && (
        <img
          src={photoUrl}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          aria-hidden="true"
        />
      )}

      {/* Dark gradient overlay for text legibility (photo case) */}
      {hasPhoto && (
        <div className="absolute inset-0 bg-gradient-to-b from-black/15 via-black/25 to-black/75" />
      )}

      <div className="absolute inset-x-0 bottom-0 z-10 px-10 pb-7 text-white">
        <div className="mb-2 text-[10px] uppercase tracking-[0.25em] opacity-85">
          {dateLabel}
        </div>
        {essenceProse && (
          <h2 className="m-0 max-w-[640px] font-serif text-[28px] font-normal leading-[1.35]">
            {essenceProse}
          </h2>
        )}
        {placeLine && (
          <div className="mt-3 flex items-center gap-1.5 text-xs opacity-75">
            <span className="text-base">◦</span>
            <span>{placeLine}</span>
          </div>
        )}
      </div>
    </div>
  );
};
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/Hero.test.tsx
```

Expected: 4 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/Hero.tsx frontend/src/__tests__/timeline/Hero.test.tsx && git commit -m "feat(frontend/timeline): immersive Hero component"
```

---

## Task 5: Frontend — `StateBand` component

**Files:**
- Create: `frontend/src/components/timeline/immersive/StateBand.tsx`
- Test: included in PeriodCard test (skipped here for atomic-component brevity — StateBand is a pure presentational div)

The state band is a 6px-tall horizontal gradient strip below the hero. It's driven by `state_bands` from the existing viewport response.

#### Step 1: Create the component

Create `frontend/src/components/timeline/immersive/StateBand.tsx`:

```typescript
import React from "react";

import type { TimelineStateBand } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";

interface StateBandProps {
  bands: TimelineStateBand[];
  periodStart: number;
  periodEnd: number;
  className?: string;
}

const VALENCE_COLOR: Record<string, string> = {
  warm: "#c9a878",
  bright: "#d4b886",
  neutral: "#a8a08a",
  cool: "#7a8898",
  tense: "#b87a78",
};

function valenceToColor(valence: number): string {
  if (valence >= 0.60) return VALENCE_COLOR.bright;
  if (valence >= 0.20) return VALENCE_COLOR.warm;
  if (valence >= -0.20) return VALENCE_COLOR.neutral;
  if (valence >= -0.50) return VALENCE_COLOR.cool;
  return VALENCE_COLOR.tense;
}

export const StateBand: React.FC<StateBandProps> = ({
  bands,
  periodStart,
  periodEnd,
  className,
}) => {
  const duration = periodEnd - periodStart;
  if (duration <= 0 || bands.length === 0) {
    return <div className={cn("h-1.5 bg-[#e8e3d8]", className)} aria-hidden="true" />;
  }

  // Build a linear gradient where each band occupies a slice proportional to its duration
  const stops: string[] = [];
  let cursor = 0;
  for (const band of bands) {
    const start = Math.max(0, ((band.time_start - periodStart) / duration) * 100);
    const end = Math.min(100, ((band.time_end - periodStart) / duration) * 100);
    const color = valenceToColor(band.valence);
    stops.push(`${color} ${start.toFixed(1)}%`);
    stops.push(`${color} ${end.toFixed(1)}%`);
    cursor = end;
  }
  // Fill remaining gap with the last color (or neutral if empty)
  if (cursor < 100) {
    const last = stops[stops.length - 1]?.split(" ")[0] ?? VALENCE_COLOR.neutral;
    stops.push(`${last} ${cursor.toFixed(1)}%`);
    stops.push(`${last} 100%`);
  }
  const background = `linear-gradient(90deg, ${stops.join(", ")})`;

  return (
    <div
      className={cn("h-1.5", className)}
      style={{ background }}
      aria-hidden="true"
    />
  );
};
```

#### Step 2: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/StateBand.tsx && git commit -m "feat(frontend/timeline): immersive StateBand component"
```

---

## Task 6: Frontend — `ThemesRow` component

**Files:**
- Create: `frontend/src/components/timeline/immersive/ThemesRow.tsx`
- Test: included in PeriodCard test

#### Step 1: Create the component

Create `frontend/src/components/timeline/immersive/ThemesRow.tsx`:

```typescript
import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineThemeCard } from "@/api/modules/timeline";

interface ThemesRowProps {
  themes: TimelineThemeCard[];
  maxThemes?: number;
}

export const ThemesRow: React.FC<ThemesRowProps> = ({ themes, maxThemes = 4 }) => {
  const { t } = useTranslation("app");
  const visible = themes.slice(0, maxThemes);

  if (visible.length === 0) return null;

  return (
    <div className="flex flex-wrap items-baseline gap-3 px-10 pt-5 pb-1">
      <span className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        {t("timeline.immersive.themesLabel", { defaultValue: "你那时关心的" })}
      </span>
      {visible.map((theme) => (
        <span
          key={theme.theme_key}
          className="border-b border-dotted border-muted-foreground/40 pb-[1px] text-[13.5px] text-foreground"
        >
          {theme.title}
        </span>
      ))}
    </div>
  );
};
```

#### Step 2: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/ThemesRow.tsx && git commit -m "feat(frontend/timeline): immersive ThemesRow component"
```

---

## Task 7: Frontend — `Slice` component (with ♡ + ⋯ gestures)

**Files:**
- Create: `frontend/src/components/timeline/immersive/Slice.tsx`
- Test: `frontend/src/__tests__/timeline/Slice.test.tsx`

The slice is the narrative unit: time range on the left, narrative + optional sensory_detail on the right, ♡ icon on hover that toggles `user_pinned` via `annotateEpisode`, ⋯ menu with a single "不算这天的样子" action that calls `forgetEpisode(id, false)`.

Props:
- `episodeId: string`
- `timeRangeLabel: string` (e.g. "14:00 – 17:00")
- `narrative: string`
- `sensoryDetail?: string`
- `isPinned: boolean`
- `onTogglePinned: (episodeId: string, nextPinned: boolean) => void | Promise<void>`
- `onHide: (episodeId: string) => void | Promise<void>`
- `pendingAction?: "pin" | "hide" | null` (for showing a subtle "saving…" state)

#### Step 1: Write the failing test

Create `frontend/src/__tests__/timeline/Slice.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { Slice } from "@/components/timeline/immersive/Slice";

const baseProps = {
  episodeId: "ep-x",
  timeRangeLabel: "14:00 – 17:00",
  narrative: "下午你读了 timeline-domain 的架构文档。",
  isPinned: false,
  onTogglePinned: vi.fn(),
  onHide: vi.fn(),
};

describe("Slice", () => {
  it("renders time range, narrative, and optional sensory detail", () => {
    render(
      <Slice
        {...baseProps}
        sensoryDetail="窗外光线很柔。"
      />
    );

    expect(screen.getByText("14:00 – 17:00")).toBeInTheDocument();
    expect(screen.getByText(/下午你读了/)).toBeInTheDocument();
    expect(screen.getByText("窗外光线很柔。")).toBeInTheDocument();
  });

  it("calls onTogglePinned with next=true when ♡ is clicked on an unpinned slice", async () => {
    const user = userEvent.setup();
    const toggle = vi.fn();
    render(<Slice {...baseProps} onTogglePinned={toggle} />);

    const heart = screen.getByRole("button", { name: /想常回来|喜欢|♡/i });
    await user.click(heart);

    expect(toggle).toHaveBeenCalledWith("ep-x", true);
  });

  it("shows a solid ♡ when isPinned is true and toggles to false on click", async () => {
    const user = userEvent.setup();
    const toggle = vi.fn();
    render(<Slice {...baseProps} isPinned onTogglePinned={toggle} />);

    const heart = screen.getByRole("button", { name: /想常回来|喜欢|♡/i });
    // Solid heart should have a "data-pinned" attribute or distinct style
    expect(heart).toHaveAttribute("data-pinned", "true");

    await user.click(heart);
    expect(toggle).toHaveBeenCalledWith("ep-x", false);
  });

  it("opens the ⋯ menu and triggers onHide", async () => {
    const user = userEvent.setup();
    const hide = vi.fn();
    render(<Slice {...baseProps} onHide={hide} />);

    const menuButton = screen.getByRole("button", { name: /more|更多|⋯/i });
    await user.click(menuButton);
    const hideItem = await screen.findByText(/不算这天的样子/);
    await user.click(hideItem);

    expect(hide).toHaveBeenCalledWith("ep-x");
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/Slice.test.tsx
```

#### Step 3: Create the component

Create `frontend/src/components/timeline/immersive/Slice.tsx`:

```typescript
import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

interface SliceProps {
  episodeId: string;
  timeRangeLabel: string;
  narrative: string;
  sensoryDetail?: string;
  isPinned: boolean;
  onTogglePinned: (episodeId: string, nextPinned: boolean) => void | Promise<void>;
  onHide: (episodeId: string) => void | Promise<void>;
  pendingAction?: "pin" | "hide" | null;
}

export const Slice: React.FC<SliceProps> = ({
  episodeId,
  timeRangeLabel,
  narrative,
  sensoryDetail,
  isPinned,
  onTogglePinned,
  onHide,
  pendingAction,
}) => {
  const { t } = useTranslation("app");
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="group grid grid-cols-[110px_1fr_auto] items-baseline gap-7 border-b border-border/30 py-5.5 last:border-b-0">
      <div className="font-mono text-xs uppercase tracking-[0.1em] text-muted-foreground">
        {timeRangeLabel}
      </div>

      <div className="max-w-[640px] text-[15.5px] leading-[1.85] text-foreground">
        {narrative}
        {sensoryDetail && (
          <span className="mt-1.5 block text-[12.5px] italic text-muted-foreground">
            {sensoryDetail}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          aria-label={t("timeline.immersive.heartLabel", { defaultValue: "想常回来" })}
          data-pinned={isPinned ? "true" : "false"}
          disabled={pendingAction === "pin"}
          onClick={() => onTogglePinned(episodeId, !isPinned)}
          className={cn(
            "text-lg transition-opacity",
            isPinned
              ? "text-[#b87a78] opacity-100"
              : "text-muted-foreground/40 opacity-0 group-hover:opacity-100 hover:text-[#b87a78]"
          )}
        >
          ♡
        </button>

        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              aria-label={t("timeline.immersive.moreLabel", { defaultValue: "更多" })}
              className="text-muted-foreground/40 opacity-0 group-hover:opacity-100"
            >
              ⋯
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={pendingAction === "hide"}
              onSelect={() => {
                setMenuOpen(false);
                void onHide(episodeId);
              }}
            >
              {t("timeline.immersive.hideMemoryLabel", { defaultValue: "不算这天的样子" })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
};
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/Slice.test.tsx
```

Expected: 4 passed.

> **If the DropdownMenu test fails** because shadcn's Radix dropdown needs `userEvent` rather than `fireEvent`, the test already uses `userEvent.setup()` — that should work. If it still fails (Radix portal rendering issue), the workaround is to use `screen.findByText(/不算这天的样子/)` (already using `findByText` for the lazy menu item).

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/Slice.tsx frontend/src/__tests__/timeline/Slice.test.tsx && git commit -m "feat(frontend/timeline): immersive Slice with ♡ + ⋯ gestures"
```

---

## Task 8: Frontend — `PeriodCard` composer

**Files:**
- Create: `frontend/src/components/timeline/immersive/PeriodCard.tsx`
- Create: `frontend/src/components/timeline/immersive/PeriodCardEmpty.tsx`
- Test: `frontend/src/__tests__/timeline/PeriodCard.test.tsx`

Composes Hero + StateBand + ThemesRow + Slice list. Handles the empty-state branch when there are no clusters.

#### Step 1: Write the failing test

Create `frontend/src/__tests__/timeline/PeriodCard.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { PeriodCard } from "@/components/timeline/immersive/PeriodCard";
import type {
  TimelineClusterBlock,
  TimelineStateBand,
  TimelineThemeCard,
  TimelineViewportResponse,
} from "@/api/modules/timeline";

function makeViewport(overrides: Partial<TimelineViewportResponse> = {}): TimelineViewportResponse {
  return {
    viewport: { scale: "day", start: 0, end: 86400, focus: 0, query: null, timezone: null },
    summary: { event_count: 0, cluster_count: 0, dominant_modes: [] },
    overview: {
      title: "5/17 周日",
      summary: "fallback summary",
      key_takeaways: [],
      essence_prose: "周日。你大部分时间在 localhost 之间游走。",
    },
    state_summary: { dominant_valence: "cool", volatility: 0.4, notable_changes: [] },
    state_bands: [],
    state_markers: [],
    source_mix: [],
    theme_cards: [],
    clusters: [],
    reflections: [],
    raw_events: [],
    ...overrides,
  } as TimelineViewportResponse;
}

describe("PeriodCard", () => {
  it("renders Hero with essence_prose from overview", () => {
    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport()}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText(/localhost/)).toBeInTheDocument();
  });

  it("renders one Slice per cluster", () => {
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        time_start: 0,
        time_end: 3600,
        label: "morning",
        slice_narrative: "上午你在调试。",
        user_pinned: false,
      } as TimelineClusterBlock,
      {
        episode_id: "ep-b",
        time_start: 7200,
        time_end: 10800,
        label: "afternoon",
        slice_narrative: "下午你换了一个新方向。",
        user_pinned: true,
      } as TimelineClusterBlock,
    ];

    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({ clusters })}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText("上午你在调试。")).toBeInTheDocument();
    expect(screen.getByText("下午你换了一个新方向。")).toBeInTheDocument();
  });

  it("renders ThemesRow when theme_cards is non-empty", () => {
    const themes: TimelineThemeCard[] = [
      { theme_key: "t1", title: "portrait rail", source_count: 0, evidence_anchors: [] } as TimelineThemeCard,
      { theme_key: "t2", title: "timeline-domain", source_count: 0, evidence_anchors: [] } as TimelineThemeCard,
    ];
    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({ theme_cards: themes })}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText("portrait rail")).toBeInTheDocument();
    expect(screen.getByText("timeline-domain")).toBeInTheDocument();
  });

  it("renders PeriodCardEmpty when viewport has zero events and zero clusters", () => {
    render(
      <PeriodCard
        scale="day"
        viewport={makeViewport({ overview: { title: "", summary: "", key_takeaways: [], essence_prose: "" } })}
        dateLabel="2026 · 5 · 17 · 周日"
        onTogglePinned={vi.fn()}
        onHide={vi.fn()}
        pendingAction={{}}
      />
    );

    expect(screen.getByText(/再陪你几天/)).toBeInTheDocument();
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/PeriodCard.test.tsx
```

#### Step 3: Create the empty state component

Create `frontend/src/components/timeline/immersive/PeriodCardEmpty.tsx`:

```typescript
import React from "react";
import { useTranslation } from "react-i18next";

interface PeriodCardEmptyProps {
  scale: "month" | "week" | "day" | "hour";
  dateLabel: string;
}

export const PeriodCardEmpty: React.FC<PeriodCardEmptyProps> = ({ scale, dateLabel }) => {
  const { t } = useTranslation("app");
  const emptyMessage =
    scale === "month"
      ? t("timeline.immersive.emptyMonth", {
          defaultValue: "月度回顾需要几周时间慢慢长出来。先从日开始翻？",
        })
      : t("timeline.immersive.emptyDay", {
          defaultValue: "再陪你几天，这页就会写满你的样子。",
        });

  return (
    <div className="flex h-[400px] flex-col items-center justify-center gap-3 px-10 text-center">
      <div className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
        {dateLabel}
      </div>
      <p className="max-w-[420px] text-sm leading-relaxed text-muted-foreground">
        {emptyMessage}
      </p>
    </div>
  );
};
```

#### Step 4: Create the composer

Create `frontend/src/components/timeline/immersive/PeriodCard.tsx`:

```typescript
import React, { useMemo } from "react";

import type { TimelineViewportResponse } from "@/api/modules/timeline";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";

import { Hero, type HeroFallbackTone } from "./Hero";
import { PeriodCardEmpty } from "./PeriodCardEmpty";
import { Slice } from "./Slice";
import { StateBand } from "./StateBand";
import { ThemesRow } from "./ThemesRow";

interface PeriodCardProps {
  scale: "month" | "week" | "day" | "hour";
  viewport: TimelineViewportResponse;
  dateLabel: string;
  placeLine?: string;
  onTogglePinned: (episodeId: string, nextPinned: boolean) => void | Promise<void>;
  onHide: (episodeId: string) => void | Promise<void>;
  pendingAction: Record<string, "pin" | "hide" | null>;
}

function formatTimeRange(startSec: number, endSec: number): string {
  const fmt = (s: number) => {
    const d = new Date(s * 1000);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  };
  return `${fmt(startSec)} – ${fmt(endSec)}`;
}

function pickHeroPhotoUrl(viewport: TimelineViewportResponse): string | null {
  // Heuristic: prefer the highest-scoring or user-pinned cluster's representative_asset_ref.
  // Plan 1+2 stored representative_asset_ref per L2 episode; cluster.episode_id maps 1:1.
  const ranked = [...(viewport.clusters || [])].sort((a, b) => {
    if (a.user_pinned !== b.user_pinned) return a.user_pinned ? -1 : 1;
    // Longer episodes first when no pin signal
    return (b.time_end - b.time_start) - (a.time_end - a.time_start);
  });
  for (const cluster of ranked) {
    const url = resolveTimelineAssetUrl(cluster.representative_asset_ref);
    if (url) return url;
  }
  return null;
}

function valenceToFallbackTone(dominant: string | undefined): HeroFallbackTone {
  const allowed: HeroFallbackTone[] = ["warm", "cool", "neutral", "bright", "tense"];
  if (dominant && (allowed as string[]).includes(dominant)) return dominant as HeroFallbackTone;
  return "neutral";
}

export const PeriodCard: React.FC<PeriodCardProps> = ({
  scale,
  viewport,
  dateLabel,
  placeLine,
  onTogglePinned,
  onHide,
  pendingAction,
}) => {
  const hasContent =
    (viewport.clusters?.length ?? 0) > 0 ||
    (viewport.summary?.event_count ?? 0) > 0 ||
    (viewport.overview?.essence_prose ?? "").length > 0;

  const photoUrl = useMemo(() => pickHeroPhotoUrl(viewport), [viewport]);
  const fallbackTone = valenceToFallbackTone(viewport.state_summary?.dominant_valence);

  if (!hasContent) {
    return <PeriodCardEmpty scale={scale} dateLabel={dateLabel} />;
  }

  return (
    <div className="bg-background">
      <Hero
        dateLabel={dateLabel}
        essenceProse={viewport.overview?.essence_prose ?? ""}
        placeLine={placeLine}
        photoUrl={photoUrl}
        fallbackTone={fallbackTone}
      />
      <StateBand
        bands={viewport.state_bands ?? []}
        periodStart={viewport.viewport.start}
        periodEnd={viewport.viewport.end}
      />
      <ThemesRow themes={viewport.theme_cards ?? []} />
      <div className="px-10 pb-7 pt-2">
        {(viewport.clusters ?? []).map((cluster) => (
          <Slice
            key={cluster.episode_id ?? `${cluster.time_start}`}
            episodeId={cluster.episode_id ?? ""}
            timeRangeLabel={formatTimeRange(cluster.time_start, cluster.time_end)}
            narrative={cluster.slice_narrative || cluster.summary || cluster.label || ""}
            sensoryDetail={cluster.slice_sensory_detail || undefined}
            isPinned={Boolean(cluster.user_pinned)}
            onTogglePinned={onTogglePinned}
            onHide={onHide}
            pendingAction={pendingAction[cluster.episode_id ?? ""] ?? null}
          />
        ))}
      </div>
    </div>
  );
};
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/PeriodCard.test.tsx
```

Expected: 4 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/PeriodCard.tsx frontend/src/components/timeline/immersive/PeriodCardEmpty.tsx frontend/src/__tests__/timeline/PeriodCard.test.tsx && git commit -m "feat(frontend/timeline): PeriodCard composer + empty state"
```

---

## Task 9: Frontend — `HourDetail` component (detective mode)

**Files:**
- Create: `frontend/src/components/timeline/immersive/HourDetail.tsx`
- Test: `frontend/src/__tests__/timeline/HourDetail.test.tsx`

Hour scale renders flat: no hero, no themes, no state band, no ♡/⋯ gestures. Just a clean list of clusters or raw events with time + source + brief description.

#### Step 1: Write the failing test

Create `frontend/src/__tests__/timeline/HourDetail.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { HourDetail } from "@/components/timeline/immersive/HourDetail";
import type { TimelineClusterBlock, TimelineViewportResponse } from "@/api/modules/timeline";

function makeViewport(clusters: TimelineClusterBlock[] = []): TimelineViewportResponse {
  return {
    viewport: { scale: "hour", start: 0, end: 3600, focus: 0, query: null, timezone: null },
    summary: { event_count: clusters.length, cluster_count: clusters.length, dominant_modes: [] },
    overview: { title: "", summary: "", key_takeaways: [] },
    state_summary: { dominant_valence: "neutral", volatility: 0, notable_changes: [] },
    state_bands: [],
    state_markers: [],
    source_mix: [],
    theme_cards: [],
    clusters,
    reflections: [],
    raw_events: [],
  } as TimelineViewportResponse;
}

describe("HourDetail", () => {
  it("renders an empty state when there are no clusters or events", () => {
    render(<HourDetail viewport={makeViewport([])} />);
    expect(screen.getByText(/这个小时|动静|empty/i)).toBeInTheDocument();
  });

  it("renders one row per cluster with time and source", () => {
    const clusters: TimelineClusterBlock[] = [
      {
        episode_id: "ep-a",
        time_start: 240,  // 00:04
        time_end: 540,    // 00:09
        label: "Chrome 浏览",
        summary: "百炼控制台 ×6",
      } as TimelineClusterBlock,
      {
        episode_id: "ep-b",
        time_start: 900,
        time_end: 950,
        label: "GitHub 浏览",
        summary: "asukaonly/magi",
      } as TimelineClusterBlock,
    ];
    render(<HourDetail viewport={makeViewport(clusters)} />);

    expect(screen.getByText(/00:04/)).toBeInTheDocument();
    expect(screen.getByText(/Chrome 浏览/)).toBeInTheDocument();
    expect(screen.getByText(/百炼控制台 ×6/)).toBeInTheDocument();

    expect(screen.getByText(/00:15/)).toBeInTheDocument();
    expect(screen.getByText(/GitHub 浏览/)).toBeInTheDocument();
  });

  it("does NOT render a Hero element", () => {
    const clusters: TimelineClusterBlock[] = [
      { episode_id: "ep-a", time_start: 100, time_end: 200, label: "x" } as TimelineClusterBlock,
    ];
    const { container } = render(<HourDetail viewport={makeViewport(clusters)} />);
    // Hero adds a <h2> with serif essence text; HourDetail should not.
    expect(container.querySelector("h2")).not.toBeInTheDocument();
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/HourDetail.test.tsx
```

#### Step 3: Create the component

Create `frontend/src/components/timeline/immersive/HourDetail.tsx`:

```typescript
import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineViewportResponse } from "@/api/modules/timeline";

interface HourDetailProps {
  viewport: TimelineViewportResponse;
}

function formatHourMinute(sec: number): string {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export const HourDetail: React.FC<HourDetailProps> = ({ viewport }) => {
  const { t } = useTranslation("app");
  const clusters = viewport.clusters ?? [];
  const rawEvents = viewport.raw_events ?? [];

  if (clusters.length === 0 && rawEvents.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">
        {t("timeline.immersive.hourEmpty", { defaultValue: "这个小时没什么动静。" })}
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/30 px-10 py-5">
      {clusters.map((c) => (
        <div
          key={c.episode_id ?? `${c.time_start}`}
          className="grid grid-cols-[110px_1fr] gap-7 py-3"
        >
          <div className="font-mono text-xs uppercase tracking-[0.08em] text-muted-foreground">
            {formatHourMinute(c.time_start)}
            <span className="opacity-60"> – {formatHourMinute(c.time_end)}</span>
          </div>
          <div>
            <div className="text-sm text-foreground">{c.label ?? ""}</div>
            {c.summary && (
              <div className="mt-1 text-xs text-muted-foreground">{c.summary}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/HourDetail.test.tsx
```

Expected: 3 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/HourDetail.tsx frontend/src/__tests__/timeline/HourDetail.test.tsx && git commit -m "feat(frontend/timeline): HourDetail detective-mode component"
```

---

## Task 10: Frontend — `MoodCalendar` sidebar widget

**Files:**
- Create: `frontend/src/components/timeline/immersive/sidebar/MoodCalendar.tsx`
- Test: `frontend/src/__tests__/timeline/MoodCalendar.test.tsx`

Renders the current month as a 7×N grid of small day cells. Each cell colored by `dominant_valence`. Today is outlined. Click a cell → calls `onSelectDate(YYYY-MM-DD)`.

#### Step 1: Write failing test

Create `frontend/src/__tests__/timeline/MoodCalendar.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { MoodCalendar } from "@/components/timeline/immersive/sidebar/MoodCalendar";

describe("MoodCalendar", () => {
  it("renders 7 weekday headers", () => {
    render(
      <MoodCalendar
        month="2026-05"
        days={[]}
        selectedDate="2026-05-17"
        onSelectDate={vi.fn()}
      />
    );
    // 7 day-of-week headers (一/二/三/四/五/六/日 or M T W T F S S — locale-dependent)
    const headers = screen.getAllByRole("columnheader");
    expect(headers.length).toBe(7);
  });

  it("highlights the selected date cell", () => {
    render(
      <MoodCalendar
        month="2026-05"
        days={[{
          date: "2026-05-17",
          dominant_valence: "cool",
          volatility: 0.6,
          event_count: 228,
          sparkline: [],
        }]}
        selectedDate="2026-05-17"
        onSelectDate={vi.fn()}
      />
    );
    const selected = screen.getByRole("button", { name: /2026-05-17/ });
    expect(selected).toHaveAttribute("data-selected", "true");
  });

  it("calls onSelectDate when a day cell is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <MoodCalendar
        month="2026-05"
        days={[
          { date: "2026-05-10", dominant_valence: "warm", volatility: 0.2, event_count: 42, sparkline: [] },
        ]}
        selectedDate="2026-05-17"
        onSelectDate={onSelect}
      />
    );
    const cell = screen.getByRole("button", { name: /2026-05-10/ });
    await user.click(cell);
    expect(onSelect).toHaveBeenCalledWith("2026-05-10");
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/MoodCalendar.test.tsx
```

#### Step 3: Create the component

Create `frontend/src/components/timeline/immersive/sidebar/MoodCalendar.tsx`:

```typescript
import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineMoodCalendarDay } from "@/api/modules/timeline";
import { cn } from "@/lib/utils";

interface MoodCalendarProps {
  month: string;  // "YYYY-MM"
  days: TimelineMoodCalendarDay[];
  selectedDate: string;
  onSelectDate: (isoDate: string) => void;
}

const VALENCE_BG: Record<string, string> = {
  warm: "bg-[#c9a878]",
  bright: "bg-[#d4b886]",
  neutral: "bg-[#a8a08a]",
  cool: "bg-[#7a8898]",
  tense: "bg-[#b87a78]",
};

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export const MoodCalendar: React.FC<MoodCalendarProps> = ({
  month,
  days,
  selectedDate,
  onSelectDate,
}) => {
  const { t } = useTranslation("app");

  const [year, monthNum] = month.split("-").map(Number);
  const firstOfMonth = new Date(year, monthNum - 1, 1);
  const daysInMonth = new Date(year, monthNum, 0).getDate();
  // Monday-start week — pad leading empties
  const leadingPad = (firstOfMonth.getDay() + 6) % 7;

  const byDate = useMemo(() => {
    const m = new Map<string, TimelineMoodCalendarDay>();
    for (const d of days) m.set(d.date, d);
    return m;
  }, [days]);

  const weekdayHeaders = ["一", "二", "三", "四", "五", "六", "日"];

  const cells: React.ReactNode[] = [];
  for (let i = 0; i < leadingPad; i++) {
    cells.push(<div key={`pad-${i}`} aria-hidden="true" />);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const date = isoDate(year, monthNum, day);
    const moodDay = byDate.get(date);
    const isSelected = date === selectedDate;
    const isToday = (() => {
      const t = new Date();
      return t.getFullYear() === year && t.getMonth() === monthNum - 1 && t.getDate() === day;
    })();

    cells.push(
      <button
        key={date}
        type="button"
        aria-label={date}
        data-selected={isSelected ? "true" : "false"}
        onClick={() => onSelectDate(date)}
        className={cn(
          "relative aspect-square rounded-sm bg-[rgba(184,177,165,0.15)]",
          isSelected && "ring-1 ring-foreground",
        )}
      >
        {moodDay && (
          <span
            className={cn(
              "absolute inset-[2px] rounded-[2px] opacity-85",
              VALENCE_BG[moodDay.dominant_valence] ?? VALENCE_BG.neutral,
            )}
            aria-hidden="true"
          />
        )}
        {isToday && (
          <span className="absolute inset-0 rounded-sm ring-[1.5px] ring-foreground/80 ring-inset" />
        )}
      </button>
    );
  }

  return (
    <div className="px-4 py-4">
      <div className="mb-2.5 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {t("timeline.immersive.moodCalendarLabel", { defaultValue: "这个月" })}
      </div>
      <div role="row" className="mb-1.5 grid grid-cols-7 gap-1 text-[9px] text-muted-foreground/80">
        {weekdayHeaders.map((label) => (
          <span key={label} role="columnheader" className="text-center">
            {label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">{cells}</div>
    </div>
  );
};
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/MoodCalendar.test.tsx
```

Expected: 3 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/sidebar/MoodCalendar.tsx frontend/src/__tests__/timeline/MoodCalendar.test.tsx && git commit -m "feat(frontend/timeline): MoodCalendar sidebar widget"
```

---

## Task 11: Frontend — `StandoutList` sidebar widget

**Files:**
- Create: `frontend/src/components/timeline/immersive/sidebar/StandoutList.tsx`
- Test: `frontend/src/__tests__/timeline/StandoutList.test.tsx`

Renders "值得回来的" — mixed Magi-curated + user-pinned items. User items prefix with ♡; Magi items have no prefix.

#### Step 1: Write failing test

Create `frontend/src/__tests__/timeline/StandoutList.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";

import { StandoutList } from "@/components/timeline/immersive/sidebar/StandoutList";
import type { TimelineStandoutItem } from "@/api/modules/timeline";

const items: TimelineStandoutItem[] = [
  {
    episode_id: "ep-1",
    scale: "day",
    start: 1,
    end: 2,
    title: "第一次跑通 ChatTaskAgent",
    date: "2026-05-12",
    source: "magi",
    score: 0.8,
  },
  {
    episode_id: "ep-2",
    scale: "day",
    start: 3,
    end: 4,
    title: "跟 Z 在文渊喝咖啡",
    date: "2026-05-14",
    source: "user",
    score: 0.0,
  },
];

describe("StandoutList", () => {
  it("renders title and date for each item", () => {
    render(<StandoutList items={items} onSelectEpisode={vi.fn()} />);
    expect(screen.getByText("第一次跑通 ChatTaskAgent")).toBeInTheDocument();
    expect(screen.getByText("2026-05-12")).toBeInTheDocument();
    expect(screen.getByText("跟 Z 在文渊喝咖啡")).toBeInTheDocument();
  });

  it("prefixes user-pinned items with ♡ and not magi items", () => {
    render(<StandoutList items={items} onSelectEpisode={vi.fn()} />);
    const userItem = screen.getByText("跟 Z 在文渊喝咖啡").closest("button");
    const magiItem = screen.getByText("第一次跑通 ChatTaskAgent").closest("button");
    expect(userItem?.textContent).toMatch(/♡/);
    expect(magiItem?.textContent).not.toMatch(/♡/);
  });

  it("calls onSelectEpisode when an item is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<StandoutList items={items} onSelectEpisode={onSelect} />);
    await user.click(screen.getByText("第一次跑通 ChatTaskAgent"));
    expect(onSelect).toHaveBeenCalledWith("ep-1");
  });

  it("renders the empty-state placeholder when items is empty", () => {
    render(<StandoutList items={[]} onSelectEpisode={vi.fn()} />);
    expect(screen.getByText(/再陪你几天/)).toBeInTheDocument();
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/StandoutList.test.tsx
```

#### Step 3: Create the component

Create `frontend/src/components/timeline/immersive/sidebar/StandoutList.tsx`:

```typescript
import React from "react";
import { useTranslation } from "react-i18next";

import type { TimelineStandoutItem } from "@/api/modules/timeline";

interface StandoutListProps {
  items: TimelineStandoutItem[];
  onSelectEpisode: (episodeId: string) => void;
}

export const StandoutList: React.FC<StandoutListProps> = ({ items, onSelectEpisode }) => {
  const { t } = useTranslation("app");

  return (
    <div className="border-t border-border/30 px-4 py-4">
      <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {t("timeline.immersive.standoutLabel", { defaultValue: "值得回来的" })}
      </div>
      {items.length === 0 ? (
        <p className="text-[12px] italic text-muted-foreground/70 leading-relaxed">
          {t("timeline.immersive.standoutEmpty", {
            defaultValue: "再陪你几天，这里会出现更多值得回来的瞬间。",
          })}
        </p>
      ) : (
        <ul className="space-y-0">
          {items.map((item) => (
            <li key={item.episode_id}>
              <button
                type="button"
                onClick={() => onSelectEpisode(item.episode_id)}
                className="block w-full border-b border-dashed border-border/40 py-2.5 text-left text-[12.5px] leading-[1.45] text-foreground/85 last:border-b-0 hover:bg-foreground/5"
              >
                {item.source === "user" && (
                  <span className="mr-1 text-[#b87a78]">♡</span>
                )}
                {item.title || t("timeline.immersive.untitledMoment", { defaultValue: "未命名" })}
                <span className="mt-0.5 block text-[10px] text-muted-foreground">
                  {item.date}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/StandoutList.test.tsx
```

Expected: 4 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/sidebar/StandoutList.tsx frontend/src/__tests__/timeline/StandoutList.test.tsx && git commit -m "feat(frontend/timeline): StandoutList sidebar widget"
```

---

## Task 12: Frontend — minimal `Toolbar` + `TimelineSidebar` composer

**Files:**
- Create: `frontend/src/components/timeline/immersive/Toolbar.tsx`
- Create: `frontend/src/components/timeline/immersive/sidebar/TimelineSidebar.tsx`

The new Toolbar is a slim header strip: scale tabs (月/周/日/时), date display + nav arrows, search input. ~80 lines max (vs the deleted TimelineToolbar's 349 lines). The TimelineSidebar composes MoodCalendar + StandoutList vertically.

#### Step 1: Create the toolbar

Create `frontend/src/components/timeline/immersive/Toolbar.tsx`:

```typescript
import React from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type ToolbarScale = "month" | "week" | "day" | "hour";

interface ToolbarProps {
  scale: ToolbarScale;
  dateLabel: string;
  draftQuery: string;
  canGoNext: boolean;
  onScaleChange: (next: ToolbarScale) => void;
  onPrevious: () => void;
  onNext: () => void;
  onDraftQueryChange: (next: string) => void;
  onSubmitQuery: () => void;
  onRefresh: () => void;
}

const SCALE_LABEL: Record<ToolbarScale, string> = {
  month: "月",
  week: "周",
  day: "日",
  hour: "时",
};

export const Toolbar: React.FC<ToolbarProps> = ({
  scale,
  dateLabel,
  draftQuery,
  canGoNext,
  onScaleChange,
  onPrevious,
  onNext,
  onDraftQueryChange,
  onSubmitQuery,
  onRefresh,
}) => {
  const { t } = useTranslation("app");

  return (
    <div className="flex h-12 items-center gap-4 border-b border-border/40 bg-background px-6">
      <h1 className="text-sm font-semibold text-foreground">
        {t("timeline.title", { defaultValue: "时间线" })}
      </h1>
      <span className="text-xs text-muted-foreground">{dateLabel}</span>

      <div className="flex-1" />

      <div className="flex rounded-md bg-foreground/5 p-0.5">
        {(Object.keys(SCALE_LABEL) as ToolbarScale[]).map((s) => (
          <button
            key={s}
            type="button"
            aria-label={SCALE_LABEL[s]}
            data-active={s === scale ? "true" : "false"}
            onClick={() => onScaleChange(s)}
            className={cn(
              "rounded-sm px-2.5 py-1 text-xs",
              s === scale
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {SCALE_LABEL[s]}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t("timeline.previousPeriod", { defaultValue: "上一段" })}
          onClick={onPrevious}
          className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5"
        >
          ‹
        </button>
        <button
          type="button"
          aria-label={t("timeline.nextPeriod", { defaultValue: "下一段" })}
          onClick={onNext}
          disabled={!canGoNext}
          className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5 disabled:cursor-not-allowed disabled:opacity-30"
        >
          ›
        </button>
      </div>

      <Input
        value={draftQuery}
        onChange={(e) => onDraftQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSubmitQuery();
        }}
        placeholder={t("timeline.searchPlaceholder", { defaultValue: "筛选当前时段" })}
        className="h-7 w-48 text-xs"
      />

      <button
        type="button"
        aria-label={t("timeline.refresh", { defaultValue: "刷新" })}
        onClick={onRefresh}
        className="rounded-md p-1 text-muted-foreground hover:bg-foreground/5"
      >
        ↻
      </button>
    </div>
  );
};
```

#### Step 2: Create the sidebar composer

Create `frontend/src/components/timeline/immersive/sidebar/TimelineSidebar.tsx`:

```typescript
import React from "react";

import type {
  TimelineMoodCalendarDay,
  TimelineStandoutItem,
} from "@/api/modules/timeline";

import { MoodCalendar } from "./MoodCalendar";
import { StandoutList } from "./StandoutList";

interface TimelineSidebarProps {
  monthForCalendar: string;  // "YYYY-MM"
  moodDays: TimelineMoodCalendarDay[];
  standoutItems: TimelineStandoutItem[];
  selectedDate: string;
  onSelectDate: (isoDate: string) => void;
  onSelectStandoutEpisode: (episodeId: string) => void;
}

export const TimelineSidebar: React.FC<TimelineSidebarProps> = ({
  monthForCalendar,
  moodDays,
  standoutItems,
  selectedDate,
  onSelectDate,
  onSelectStandoutEpisode,
}) => {
  return (
    <aside className="w-[260px] shrink-0 overflow-y-auto border-r border-border/40 bg-[#f4ede0]">
      <MoodCalendar
        month={monthForCalendar}
        days={moodDays}
        selectedDate={selectedDate}
        onSelectDate={onSelectDate}
      />
      <StandoutList
        items={standoutItems}
        onSelectEpisode={onSelectStandoutEpisode}
      />
    </aside>
  );
};
```

#### Step 3: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/components/timeline/immersive/Toolbar.tsx frontend/src/components/timeline/immersive/sidebar/TimelineSidebar.tsx && git commit -m "feat(frontend/timeline): minimal Toolbar + TimelineSidebar composer"
```

---

## Task 13: Frontend — rewrite `Timeline.tsx` page

**Files:**
- Modify: `frontend/src/pages/Timeline.tsx` (wholesale rewrite, ~250 lines)
- Test: `frontend/src/__tests__/timeline/TimelinePageImmersive.test.tsx`

The new page:
- Default scale: `day`
- Layout: `<Toolbar /> <TimelineSidebar /> {PeriodCard or HourDetail}`
- Removes drawer + calibration handlers
- Wires sidebar `onSelectDate` to update viewport range
- Wires Slice ♡ to `memoryApi.annotateEpisode(episodeId, {user_pinned: true})` and ⋯ to `memoryApi.forgetEpisode(episodeId, false)`
- Fetches viewport + standout + mood calendar on mount and on relevant state changes

#### Step 1: Write the failing integration test

Create `frontend/src/__tests__/timeline/TimelinePageImmersive.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the API client
vi.mock("@/api/modules/timeline", async () => {
  const actual = await vi.importActual<typeof import("@/api/modules/timeline")>(
    "@/api/modules/timeline"
  );
  return {
    ...actual,
    timelineApi: {
      getViewport: vi.fn(),
      getContext: vi.fn(),
      getStandout: vi.fn(),
      getMoodCalendar: vi.fn(),
    },
  };
});

vi.mock("@/api/modules/memory", () => ({
  memoryApi: {
    annotateEpisode: vi.fn(),
    forgetEpisode: vi.fn(),
  },
}));

import { timelineApi } from "@/api/modules/timeline";
import { TimelinePage } from "@/pages/Timeline";

describe("TimelinePage (immersive)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (timelineApi.getViewport as any).mockResolvedValue({
      viewport: { scale: "day", start: 0, end: 86400, focus: 0, query: null, timezone: null },
      summary: { event_count: 1, cluster_count: 1, dominant_modes: [] },
      overview: {
        title: "test day",
        summary: "",
        key_takeaways: [],
        essence_prose: "周日。你大部分时间在 localhost 之间游走。",
      },
      state_summary: { dominant_valence: "cool", volatility: 0.4, notable_changes: [] },
      state_bands: [],
      state_markers: [],
      source_mix: [],
      theme_cards: [],
      clusters: [{
        episode_id: "ep-a",
        time_start: 100,
        time_end: 200,
        label: "x",
        slice_narrative: "narrative",
        user_pinned: false,
      }],
      reflections: [],
      raw_events: [],
    });
    (timelineApi.getStandout as any).mockResolvedValue({ month: null, items: [] });
    (timelineApi.getMoodCalendar as any).mockResolvedValue({ month: "2026-05", days: [] });
  });

  it("renders the immersive page with essence_prose on initial load", async () => {
    render(<TimelinePage />);

    await waitFor(() => {
      expect(screen.getByText(/localhost/)).toBeInTheDocument();
    });
  });

  it("defaults to day scale on mount", async () => {
    render(<TimelinePage />);

    await waitFor(() => {
      expect(timelineApi.getViewport).toHaveBeenCalled();
    });
    const call = (timelineApi.getViewport as any).mock.calls[0][0];
    expect(call.scale).toBe("day");
  });

  it("does not render a TimelineContextDrawer", () => {
    render(<TimelinePage />);
    // The old drawer used 'context_drawer' or similar test ids. The new page must NOT have it.
    expect(document.querySelector("[data-testid='timeline-context-drawer']")).toBeNull();
  });
});
```

#### Step 2: Run, expect failure

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/TimelinePageImmersive.test.tsx
```

#### Step 3: Rewrite `Timeline.tsx`

Replace the entire contents of `frontend/src/pages/Timeline.tsx` with:

```typescript
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import { memoryApi } from "@/api/modules/memory";
import {
  timelineApi,
  type TimelineMoodCalendarDay,
  type TimelineStandoutItem,
  type TimelineViewportResponse,
} from "@/api/modules/timeline";
import { HourDetail } from "@/components/timeline/immersive/HourDetail";
import { PeriodCard } from "@/components/timeline/immersive/PeriodCard";
import { Toolbar } from "@/components/timeline/immersive/Toolbar";
import { TimelineSidebar } from "@/components/timeline/immersive/sidebar/TimelineSidebar";
import { LoadingSpinner } from "@/components/ui/loading-spinner";
import { useChatShellStore } from "@/stores";

type TimelineScale = "month" | "week" | "day" | "hour";

const padNumber = (value: number): string => String(value).padStart(2, "0");
const toUnixSeconds = (date: Date): number => Math.floor(date.getTime() / 1000);

const startOfLocalHour = (date: Date): Date =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate(), date.getHours());
const startOfLocalDay = (date: Date): Date =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate());
const startOfLocalMonth = (date: Date): Date => new Date(date.getFullYear(), date.getMonth(), 1);
const startOfLocalWeek = (date: Date): Date => {
  const day = startOfLocalDay(date);
  const mondayOffset = (day.getDay() + 6) % 7;
  day.setDate(day.getDate() - mondayOffset);
  return day;
};

const shiftPeriodDate = (scale: TimelineScale, start: Date, amount: number): Date => {
  const next = new Date(start);
  if (scale === "month") next.setMonth(next.getMonth() + amount);
  if (scale === "week") next.setDate(next.getDate() + amount * 7);
  if (scale === "day") next.setDate(next.getDate() + amount);
  if (scale === "hour") next.setHours(next.getHours() + amount);
  return next;
};

const getLatestCompletePeriodStart = (scale: TimelineScale, now = new Date()): number => {
  if (scale === "month") return toUnixSeconds(shiftPeriodDate(scale, startOfLocalMonth(now), -1));
  if (scale === "week") return toUnixSeconds(shiftPeriodDate(scale, startOfLocalWeek(now), -1));
  if (scale === "day") return toUnixSeconds(shiftPeriodDate(scale, startOfLocalDay(now), -1));
  return toUnixSeconds(shiftPeriodDate(scale, startOfLocalHour(now), -1));
};
const getPeriodEnd = (scale: TimelineScale, start: number): number =>
  toUnixSeconds(shiftPeriodDate(scale, new Date(start * 1000), 1));
const shiftPeriodStart = (scale: TimelineScale, start: number, amount: number): number =>
  toUnixSeconds(shiftPeriodDate(scale, new Date(start * 1000), amount));
const clampToLatestCompletePeriod = (scale: TimelineScale, start: number): number =>
  Math.min(start, getLatestCompletePeriodStart(scale));

function formatWindowLabel(scale: TimelineScale, start: number, end: number, locale: string): string {
  const s = new Date(start * 1000);
  if (scale === "month")
    return s.toLocaleDateString(locale, { year: "numeric", month: "long" });
  if (scale === "day")
    return s.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric", weekday: "short" });
  if (scale === "hour") {
    const e = new Date(end * 1000);
    const day = s.toLocaleDateString(locale, { month: "short", day: "numeric" });
    const startTime = s.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
    const endTime = e.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
    return `${day} ${startTime}–${endTime}`;
  }
  const e = new Date(Math.max(start, end - 1) * 1000);
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const sf = s.toLocaleDateString(locale, opts);
  const ef = e.toLocaleDateString(locale, opts);
  return sf === ef ? sf : `${sf} – ${ef}`;
}

function monthKeyForDate(timestampSec: number): string {
  const d = new Date(timestampSec * 1000);
  return `${d.getFullYear()}-${padNumber(d.getMonth() + 1)}`;
}

function isoDateForTimestamp(timestampSec: number): string {
  const d = new Date(timestampSec * 1000);
  return `${d.getFullYear()}-${padNumber(d.getMonth() + 1)}-${padNumber(d.getDate())}`;
}

export const TimelinePage: React.FC = () => {
  const { t, i18n } = useTranslation("app");
  const timelineLocale = i18n.resolvedLanguage || i18n.language || "en";
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);

  const [scale, setScale] = useState<TimelineScale>("day");
  const [viewportStart, setViewportStart] = useState<number>(
    () => getLatestCompletePeriodStart("day"),
  );
  const [viewport, setViewport] = useState<TimelineViewportResponse | null>(null);
  const [moodDays, setMoodDays] = useState<TimelineMoodCalendarDay[]>([]);
  const [standoutItems, setStandoutItems] = useState<TimelineStandoutItem[]>([]);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState<Record<string, "pin" | "hide" | null>>({});

  const viewportEnd = getPeriodEnd(scale, viewportStart);
  const latestPeriodStart = getLatestCompletePeriodStart(scale);
  const canGoNext = shiftPeriodStart(scale, viewportStart, 1) <= latestPeriodStart;
  const dateLabel = formatWindowLabel(scale, viewportStart, viewportEnd, timelineLocale);

  const loadViewport = useCallback(async () => {
    setLoading(true);
    try {
      const response = await timelineApi.getViewport({
        scale,
        start: viewportStart,
        end: viewportEnd,
        query: query || undefined,
        locale: timelineLocale,
        focus: "self",
      });
      setViewport(response);
    } catch (error: any) {
      toast.error(
        t("timeline.errors.loadFailed", {
          message: error?.message || "unknown",
          defaultValue: "Failed to load timeline",
        })
      );
    } finally {
      setLoading(false);
    }
  }, [scale, viewportStart, viewportEnd, query, timelineLocale, t]);

  const loadSidebar = useCallback(async () => {
    const month = monthKeyForDate(viewportStart);
    try {
      const [mood, standout] = await Promise.all([
        timelineApi.getMoodCalendar(month),
        timelineApi.getStandout(month, 50),
      ]);
      setMoodDays(mood.days ?? []);
      setStandoutItems(standout.items ?? []);
    } catch {
      /* sidebar is best-effort; failures don't block the main pane */
    }
  }, [viewportStart]);

  useEffect(() => {
    setActivePanel("timeline");
  }, [setActivePanel]);

  useEffect(() => {
    void loadViewport();
  }, [loadViewport]);

  useEffect(() => {
    void loadSidebar();
  }, [loadSidebar]);

  const handleTogglePinned = async (episodeId: string, nextPinned: boolean) => {
    setPendingAction((s) => ({ ...s, [episodeId]: "pin" }));
    try {
      await memoryApi.annotateEpisode(episodeId, { user_pinned: nextPinned });
      // Optimistic local update so the ♡ flips immediately
      setViewport((current) => {
        if (!current) return current;
        return {
          ...current,
          clusters: current.clusters.map((c) =>
            c.episode_id === episodeId ? { ...c, user_pinned: nextPinned } : c
          ),
        };
      });
      // Refresh the standout list since this changes its contents
      await loadSidebar();
    } catch (error: any) {
      toast.error(
        t("timeline.errors.feedbackFailed", {
          message: error?.message || "unknown",
          defaultValue: "Failed to update",
        })
      );
    } finally {
      setPendingAction((s) => ({ ...s, [episodeId]: null }));
    }
  };

  const handleHide = async (episodeId: string) => {
    setPendingAction((s) => ({ ...s, [episodeId]: "hide" }));
    try {
      await memoryApi.forgetEpisode(episodeId, false);
      // Remove from local viewport
      setViewport((current) => {
        if (!current) return current;
        return {
          ...current,
          clusters: current.clusters.filter((c) => c.episode_id !== episodeId),
        };
      });
      await loadSidebar();
      toast.success(
        t("timeline.immersive.hideConfirm", { defaultValue: "已隐藏" })
      );
    } catch (error: any) {
      toast.error(
        t("timeline.errors.feedbackFailed", {
          message: error?.message || "unknown",
          defaultValue: "Failed to hide",
        })
      );
    } finally {
      setPendingAction((s) => ({ ...s, [episodeId]: null }));
    }
  };

  const handleSelectDate = (isoDate: string) => {
    const [y, m, d] = isoDate.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    const newStart = scale === "day" ? toUnixSeconds(startOfLocalDay(dt))
      : scale === "hour" ? toUnixSeconds(startOfLocalHour(dt))
      : scale === "week" ? toUnixSeconds(startOfLocalWeek(dt))
      : toUnixSeconds(startOfLocalMonth(dt));
    setViewportStart(clampToLatestCompletePeriod(scale, newStart));
  };

  const handleScaleChange = (next: TimelineScale) => {
    setScale(next);
    setViewportStart(getLatestCompletePeriodStart(next));
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      <Toolbar
        scale={scale}
        dateLabel={dateLabel}
        draftQuery={draftQuery}
        canGoNext={canGoNext}
        onScaleChange={handleScaleChange}
        onPrevious={() => setViewportStart((v) => shiftPeriodStart(scale, v, -1))}
        onNext={() =>
          setViewportStart((v) =>
            clampToLatestCompletePeriod(scale, shiftPeriodStart(scale, v, 1))
          )
        }
        onDraftQueryChange={setDraftQuery}
        onSubmitQuery={() => setQuery(draftQuery.trim())}
        onRefresh={() => void loadViewport()}
      />

      <div className="flex min-h-0 flex-1">
        <TimelineSidebar
          monthForCalendar={monthKeyForDate(viewportStart)}
          moodDays={moodDays}
          standoutItems={standoutItems}
          selectedDate={isoDateForTimestamp(viewportStart)}
          onSelectDate={handleSelectDate}
          onSelectStandoutEpisode={(episodeId) => {
            // Plan 3: scroll/highlight that episode within the current viewport.
            // For now: just refresh and let the user see the page. A jump-to-day
            // affordance can come in Plan 4.
            void episodeId;
          }}
        />

        <main className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoadingSpinner className="h-4 w-4" />
              {t("timeline.loading", { defaultValue: "加载中" })}
            </div>
          ) : viewport ? (
            scale === "hour" ? (
              <HourDetail viewport={viewport} />
            ) : (
              <PeriodCard
                scale={scale}
                viewport={viewport}
                dateLabel={dateLabel}
                onTogglePinned={handleTogglePinned}
                onHide={handleHide}
                pendingAction={pendingAction}
              />
            )
          ) : null}
        </main>
      </div>
    </div>
  );
};

export default TimelinePage;
```

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/TimelinePageImmersive.test.tsx
```

Expected: 3 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/pages/Timeline.tsx frontend/src/__tests__/timeline/TimelinePageImmersive.test.tsx && git commit -m "feat(frontend/timeline): rewrite Timeline.tsx as immersive page"
```

---

## Task 14: Frontend — i18n keys (zh-CN)

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`

Add the new `timeline.immersive.*` keys so they're picked up by `useTranslation` and the `defaultValue` fallbacks become explicit. (The components already provide `defaultValue` fallbacks, so this task is technically cosmetic — but keeping i18n explicit is a repo convention.)

#### Step 1: Locate the existing timeline block

```bash
grep -n "\"timeline\":" /Users/asuka/code/magi/frontend/src/i18n/locales/zh-CN/app.json
```

Note the line number — you'll insert the new `immersive` block inside the existing `"timeline": { ... }`.

#### Step 2: Add the keys

Inside the existing `"timeline": { ... }` block in `frontend/src/i18n/locales/zh-CN/app.json`, add:

```json
    "immersive": {
      "themesLabel": "你那时关心的",
      "moodCalendarLabel": "这个月",
      "standoutLabel": "值得回来的",
      "standoutEmpty": "再陪你几天，这里会出现更多值得回来的瞬间。",
      "untitledMoment": "未命名",
      "heartLabel": "想常回来",
      "moreLabel": "更多",
      "hideMemoryLabel": "不算这天的样子",
      "hideConfirm": "已隐藏",
      "hourEmpty": "这个小时没什么动静。",
      "emptyDay": "再陪你几天，这页就会写满你的样子。",
      "emptyMonth": "月度回顾需要几周时间慢慢长出来。先从日开始翻？"
    },
```

(Match indentation and trailing comma rules of the surrounding JSON.)

#### Step 3: Smoke-check JSON validity

```bash
cd /Users/asuka/code/magi && python -c "import json; json.load(open('frontend/src/i18n/locales/zh-CN/app.json'))" && echo "JSON OK"
```

Expected: `JSON OK`.

#### Step 4: Commit

```bash
cd /Users/asuka/code/magi && git add frontend/src/i18n/locales/zh-CN/app.json && git commit -m "feat(frontend/i18n): add timeline.immersive.* zh-CN keys"
```

---

## Task 15: Frontend — delete dead components

**Files (DELETE):**
- `frontend/src/components/timeline/TimelineContextDrawer.tsx`
- `frontend/src/components/timeline/TimelineToolbar.tsx`
- `frontend/src/components/timeline/MonthOverviewLane.tsx`
- `frontend/src/components/timeline/DayClusterLane.tsx`
- `frontend/src/components/timeline/HourDetailLane.tsx`
- `frontend/src/components/timeline/StateBandOverlay.tsx`
- `frontend/src/components/timeline/HighlightCards.tsx`
- `frontend/src/components/timeline/TimelineViewport.tsx`
- `frontend/src/__tests__/timelinePage.test.tsx`

- [ ] **Step 1: Confirm nothing else imports them**

```bash
cd /Users/asuka/code/magi/frontend && for f in TimelineContextDrawer TimelineToolbar MonthOverviewLane DayClusterLane HourDetailLane StateBandOverlay HighlightCards TimelineViewport; do
  echo "=== $f ==="
  grep -rn "from.*$f\|import.*$f" src/ --include='*.ts' --include='*.tsx' | grep -v "$f\\.tsx:" | grep -v __tests__
done
```

If any non-test import remains, fix that file first (it should be importing from the new `immersive/` tree instead).

- [ ] **Step 2: Delete the files**

```bash
cd /Users/asuka/code/magi && rm \
  frontend/src/components/timeline/TimelineContextDrawer.tsx \
  frontend/src/components/timeline/TimelineToolbar.tsx \
  frontend/src/components/timeline/MonthOverviewLane.tsx \
  frontend/src/components/timeline/DayClusterLane.tsx \
  frontend/src/components/timeline/HourDetailLane.tsx \
  frontend/src/components/timeline/StateBandOverlay.tsx \
  frontend/src/components/timeline/HighlightCards.tsx \
  frontend/src/components/timeline/TimelineViewport.tsx \
  frontend/src/__tests__/timelinePage.test.tsx
```

- [ ] **Step 3: Typecheck and run tests to confirm no broken imports**

```bash
cd /Users/asuka/code/magi/frontend && npx tsc --noEmit 2>&1 | tail -20
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/ 2>&1 | tail -5
```

Expected: no new TS errors caused by the deletions; all `src/__tests__/timeline/` tests pass.

- [ ] **Step 4: Commit**

```bash
cd /Users/asuka/code/magi && git add -A frontend/src/components/timeline/ frontend/src/__tests__/ && git commit -m "chore(frontend/timeline): remove drawer + dashboard-era components"
```

---

## Task 16: Final sweep

**Files:** none modified — validation only.

- [ ] **Step 1: Backend test sweep**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest \
  tests/api/test_timeline_viewport.py \
  tests/api/test_timeline_asset_route.py \
  tests/api/test_timeline_standout.py \
  tests/api/test_timeline_mood_calendar.py \
  --no-header 2>&1 | tail -5
```

Expected: all pass. Plan 1 + Plan 3 backend additions all green.

- [ ] **Step 2: Frontend test sweep**

```bash
cd /Users/asuka/code/magi/frontend && npx vitest run src/__tests__/timeline/ --reporter=verbose 2>&1 | tail -20
```

Expected: all immersive tests pass.

- [ ] **Step 3: TypeScript strict check**

```bash
cd /Users/asuka/code/magi/frontend && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no new errors. If TS strict surfaces issues from the new components, fix inline.

- [ ] **Step 4: Lint**

```bash
cd /Users/asuka/code/magi/frontend && npx eslint src/components/timeline/immersive src/pages/Timeline.tsx src/api/modules/timeline.ts 2>&1 | tail -20
```

Expected: no new errors.

- [ ] **Step 5: API contract checks**

```bash
cd /Users/asuka/code/magi && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python scripts/check-api-contract.py 2>&1 | tail -3
cd /Users/asuka/code/magi && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python scripts/check-sqlite-ownership.py 2>&1 | tail -3
```

Expected: `Gateway API contract check passed` and `SQLite ownership check passed`.

- [ ] **Step 6: Final commit if any fixes**

If you had to adjust anything during the sweep:

```bash
cd /Users/asuka/code/magi && git status
git add -A && git commit -m "fix(timeline): typecheck/lint fixes after Plan 3 sweep"
```

---

## Acceptance criteria for Plan 3

- `/timeline` page loads with `scale=day` by default, showing the latest complete day's PeriodCard.
- PeriodCard renders Hero with photo (when `representative_asset_ref` resolves) or warm gradient fallback (when not).
- Hero displays the period's `essence_prose` from L3 (if Plan 2's scheduler has populated it).
- Each slice shows its `slice_narrative` + optional `slice_sensory_detail` from L2 episode.
- Hovering a slice reveals ♡ + ⋯; ♡ toggles `user_pinned` via `annotateEpisode`; ⋯ → "不算这天的样子" calls `forgetEpisode(id, false)`.
- Sidebar shows MoodCalendar (current month's days colored by valence) + 值得回来的 list (mixed Magi-curated + user-pinned, ♡ prefix on user items).
- Switching to scale=hour shows the flat HourDetail list with no hero/themes/♡/⋯.
- `TimelineContextDrawer` no longer exists in the codebase.
- All dashboard-era lane components (MonthOverviewLane, DayClusterLane, etc.) removed.
- `/api/timeline/asset/{ref:path}` resolves `photo-library://` refs (or returns 404 cleanly for unknown ones).
- All Plan-3-touched tests pass; `tsc --noEmit` clean; lint clean; contract checks pass; no Plan 1/2 regression.

## Where to go after Plan 3

Plan 4 candidates surfaced during Plan 3:
- **On-demand diary generation endpoint** for historical periods that never got scheduler coverage
- **HEIC → JPEG transcoding** server-side for non-Safari browsers
- **English i18n** for `timeline.immersive.*`
- **Hour view drilldown** from the standout sidebar (clicking a standout item jumps to its day or hour)
- **Localized day boundaries** in the `/standout` `date` field (currently UTC, per Plan 1 review note)
- **Index follow-up** for `idx_episodes_standout` once standout volume grows (per Plan 1 EXPLAIN QUERY PLAN observation)
- **Real `unified_memory.media_source_registry` accessor** + state-shift signal wiring for standout scorer
