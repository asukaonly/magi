# Timeline Immersive Redesign — Design Spec

**Status:** brainstormed, ready for implementation plan
**Date:** 2026-05-19
**Owner:** asuka

## Why

The current `/timeline` page implements its underlying review-surface contract (see [timeline-domain-architecture.md](../../timeline-domain-architecture.md) §"Review Surface Product Contract") as a **memory-debug dashboard**: dense metric bars, raw L1 events, internal IDs, repeated source tags, markdown-literal summaries. Users open the page and see Magi's internal state, not their own life.

We want to redesign it as a **personal review workspace that triggers memory immersion** — opening a period should feel like flipping back to that time, not reading a report. The keyword is *涌现*: the user lands on a window and the texture of that period (mood, location, what they cared about, who they were with) arrives in the first second.

This is a wholesale visual + interaction redesign of the timeline frontend. The backend introduces the first LLM-generated narrative for L2 episodes, two new lightweight read-models (`standout` and `daily_mood_aggregate`), and lifts media-asset selection out of the photo-library plugin into a small dedicated layer — details in §"Backend implications".

## Non-goals

- **No backend memory-system changes.** Lifecycle memory (L1/L2/L3/L4), ingestion, the `TimelineEvent` model, the insight pipeline, and clustering rules are out of scope.
- **No new sensor work.** The existing `photo-library` plugin already provides photos with EXIF/geocode; we consume it.
- **No "memory page" implementation.** This spec moves calibration features *out* of timeline; building their new home is a separate effort.
- **No changes to the hour-scale clustering algorithm** beyond display.
- **No internationalization rewrite.** Existing `i18n` keys can be renamed or added, but the locale infrastructure stays.

## Product positioning

| | Before (current implementation) | After (this spec) |
|---|---|---|
| Mental model | Dashboard / memory debug panel | "Re-living" a period — a diary you didn't write yourself |
| Primary content | Markdown summary blob + metric bars + flat event list | Hero (photo or atmospheric gradient) + 2nd-person diary essence + themes + 3–5 narrative slices |
| User animations | Confirm/reject assertions, annotate episodes | Read, hover ♡ to mark "值得回来的", drill down by scale |
| Voice | None (mechanical text) | 2nd-person diary ("你那天傍晚反复打开 GitHub…") for month/week/day; bare evidence for hour |
| Feedback loops | Visible (drawer buttons, confidence pills) | Removed — calibration belongs to the future Memory page |

## Scope

### In scope

1. Rewrite [`frontend/src/pages/Timeline.tsx`](../../../frontend/src/pages/Timeline.tsx) and the timeline components under [`frontend/src/components/timeline/`](../../../frontend/src/components/timeline) for the new anatomy.
2. New left sidebar inside the timeline page (mood calendar + "值得回来的" list).
3. New hero treatment with photo / atmospheric-gradient fallback, geocoded place line.
4. New 2nd-person diary voice for month/week/day overview text — implemented in the **backend** L3-summary / overview prompt path; the frontend just renders.
5. "侦探模式" redesign of the hour scale.
6. New ♡ "值得回来的" mechanic: hover-on-slice gesture, mixed Magi-auto + user-added list, single section.
7. Hide-episode gesture, retained but visually de-emphasized (hover/menu, not a drawer button).
8. Removal of `TimelineContextDrawer` and its in-page assertion-feedback/episode-annotation UI.
9. New empty-state copy and skeleton across all scales.
10. Default landing scale switched from `month` to `day` (latest complete day).

### Explicitly out of scope

- Memory-page surface where calibration features move to.
- New L2 assertion or episode UX (the affordances simply leave timeline; the underlying APIs stay).
- Cross-page navigation patterns (e.g., "from Memory page entity → timeline filtered by entity") — designed later.
- Persona-specific voice variations of the diary essence (we use a single 2nd-person neutral-warm voice for v1).
- Search / filter / lens features (the search box stays but its UX isn't reimagined here).

## Anatomy of a "Period Card"

The same anatomy applies to **month, week, and day** scales. Hour is a different mode (see §Hour).

```
┌────────────────────────────────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │  ← Hero
│ ░░░░░░░░░░░░░░░░░ photo OR gradient ░░░░░░░░░░░░░░░░░░░░░ │     280px (day)
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │     320px (week/month)
│  2026 · 5 · 17 · 周日                                       │
│  跟一个记忆系统较劲的周日。深夜还亮着屏。                       │
│  ◦ 家 · 楼下咖啡店                                            │
├────────────────────────────────────────────────────────────────┤
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │  ← State band (6px)
├────────────────────────────────────────────────────────────────┤
│ 你那时关心的  · portrait rail · timeline-domain · 长期记忆     │  ← Themes row
│                                                                │
│ 14:00 ─ 17:00   下午你读了 timeline-domain 的架构文档…    ♡   │  ← Slices
│ 22:00 ─ 00:30   又一次打开 GitHub，刷新那个 PR…             │
│ ...                                                            │
└────────────────────────────────────────────────────────────────┘
```

### Hero

- **Photo case:** full-bleed image, `background-size: cover`, dark-bottom gradient overlay so white text is legible.
- **Fallback (no photo):** a mood-derived warm gradient (palette tied to dominant valence/state band). Same height, same text layout.
- **Photo selection:** for **day**, the photo-library plugin's representative photo for that day (heuristic: largest cluster of photos taken that day, prefer outdoor/with-people, defer to first photo if no better signal). For **week**, the representative day's photo. For **month**, a small collage (TBD in v1 — start with a single representative photo, can iterate later).
- **Text overlay:** date stamp (small uppercase), 1–3 sentence diary essence (Cormorant Garamond / Songti SC, serif), optional place line ("◦ 家 · 楼下咖啡店") derived from EXIF geocode.

### State band

A 6px horizontal band immediately below hero. Continuous gradient stops correspond to time positions within the window; color per stop is the dominant valence/state at that moment. Replaces the current three independent metric bars (情绪/压力/参与度), which are removed entirely from this page.

Hover reveals a tooltip with the state-marker label at that point (uses existing `state_markers` data).

### Themes row

The existing `theme_cards` data, rendered as a single horizontal text-only row with dotted underline. Label "你那时关心的" prefixes. No card UI, no tags, no source counts.

### Slices

The narrative units. Each slice is one row:
- left column (~100px): time range (`14:00 ─ 17:00`)
- right column: 1–2 sentences of 2nd-person prose + an optional sensory `slice-detail` italic line
- trailing: ♡ icon (invisible until hover; see §"值得回来的")

Number of slices per scale:
- **day:** 3–6
- **week:** 5–8, ordered by day
- **month:** 4–8, ordered by week-or-prominence

Slices are derived from clusters (existing `clusters` field) but **the slice text is new** — see §"Voice and writing".

## Hour scale — Detective mode

Hour is intentionally **not** a narrative period card. The user has drilled in to see what actually happened. Design rules:

- **No hero**, no diary essence, no state band, no themes row.
- A flat vertical list of cluster rows (existing `clusters` or fallback `raw_events`), each row:
  ```
  00:04 ─ 00:09   Chrome 浏览 · 百炼控制台 (6)
                  浏览了 "通义千问 API 文档" 等 3 个页面
  ```
- Source filter chips at top (existing `source_mix`), multi-select to narrow.
- No ♡, no hide gesture (these affect *episodes* / *days*, not individual raw events).
- No `TimelineContextDrawer` (removed page-wide).

## Sidebar

Width: 260px (matches current). Persistent (not collapsible in v1).

Two sections, top-to-bottom:

### 1. 这个月 — mood calendar

A 7×~5 grid of small day cells for the **current calendar month**. Each cell is either empty (no data) or filled with a mood color (warm / bright / neutral / cool / tense, per the existing tone-to-valence mapping). Today has a thin ink-colored outline. Click a cell to set the day-scale viewport to that day.

Out of v1: previous/next month navigation in this widget (the toolbar's scale+date navigation handles cross-month).

### 2. 值得回来的

A mixed list of standout moments — Magi-auto-curated by default, user-added by ♡. Both sources live in the same list, ordered by date desc. Visual mark:

- Magi-curated items: no prefix
- User-added items: `♡ ` prefix in muted warm-red, no other label

Each item shows: title (1 line) + small date line below. Up to 5 visible by default; "12 ↗ 查看全部" link at the top-right when there are more.

Day 1 behavior: shows the single Magi-auto seed "你今天第一次打开 Magi" plus the italic placeholder "再陪你几天，这里会出现更多值得回来的瞬间。"

### Magi-auto-curation logic (initial heuristic, refineable later)

A backend service picks "standout" moments from the existing data. Initial signals:
- Cluster duration > 90 minutes
- Cluster has photos (from `photo-library` sensor)
- State-shift markers within the cluster (existing `state_markers`)
- Cluster spans an L2 episode boundary that is the **first occurrence** of an entity (graph: first appearance of a person, place, or project)
- Manual `pinned` items always included

Cap at ~50 per month; older items can be demoted but kept queryable for "查看全部".

## "值得回来的" mechanic (slice ♡)

On any slice (day/week/month scales — NOT hour), hovering reveals a trailing ♡ icon at low opacity. Click toggles "added to 值得回来的":

- unmarked → unmarked ♡ visible on hover only
- marked → solid warm-red ♡, always visible (also visible without hover)
- click marked → unmarks, no confirmation

No toast, no modal. The sidebar list updates next render.

Persistence: marked-slices go through the existing L2 episode `user_pinned` annotation API (`memoryApi.annotateEpisode`). The handler chain is the same as today's `handleEpisodeAnnotation` but with a smaller payload.

## Hide gesture

The episode-hide capability (existing `memoryApi.forgetEpisode(episodeId, false)`) is retained but moved off the drawer:

- Each slice gains a hover-revealed `⋯` menu trigger (16px, opacity ~0.4)
- Menu has exactly one item in v1: "**不算这天的样子**" (label TBD; semantically = L2 episode invalidation, source L1 events untouched per the existing architecture doc lines 161–163)
- After click, brief inline confirmation ("已隐藏 · 撤销") for 4 seconds, then collapses

`forgetEpisode(id, true)` (L1 hard delete) is **NOT** exposed on this page — it belongs to a settings/memory surface.

## Voice and writing

The 2nd-person diary essence is **prose generated by Magi**, not template-stitched fields. Generation rules:

- Voice: 2nd-person ("你"), warm-neutral, no persona signature
- Length:
  - Day essence: 1–2 sentences (max ~50 chars)
  - Week essence: 2–3 sentences
  - Month essence: 3–4 sentences
- Slice text: 1 sentence narrative + optional 1 italic sentory-detail sentence ("那时你还没把答案找出来。")
- Forbidden patterns:
  - Internal IDs
  - Markdown headers (`## 要点`)
  - Source-name repetition ("Chrome 历史 / Chrome 历史")
  - Numeric metrics in the prose ("情绪 62%")

Generation lives in the backend overview/digest pipeline. The frontend trusts the strings and renders verbatim. Cached per scale+window; regenerated when underlying L1/L2 data shifts materially (existing invalidation logic in [`backend/src/magi/timeline/`](../../../backend/src/magi/timeline/) extends naturally).

## Empty states

| Where | Empty case | Treatment |
|---|---|---|
| Main pane, scale = day, no events | first-day user, sensors not yet caught up | A skeleton period card with placeholder bars where hero/essence/slices would be, plus warm text: "再陪你几天，这页就会写满你的样子。" |
| Main pane, scale = month, no L3 reflection yet | new user opens month | Same skeleton; sub-text: "月度回顾需要几周时间慢慢长出来。先从日开始翻？" with a button to switch scale to day |
| Sidebar, mood calendar | new user | Calendar grid renders with empty cells; today's cell shows a single neutral dot |
| Sidebar, 值得回来的 | new user | Single Magi-auto seed item ("你今天第一次打开 Magi") + italic placeholder |
| Hour scale, no events | (rare) | "这个小时没什么动静。" |

## Default landing

When the user opens `/timeline`, default `scale = day`, default `viewportStart = latest complete day` (i.e., yesterday in local timezone). Current behavior is `scale = month`, latest complete month — change at [`Timeline.tsx:131-132`](../../../frontend/src/pages/Timeline.tsx#L131).

## Backend implications

### Current state worth knowing

The reader should approach the changes below with three facts about the existing system in mind:

1. **L2 episode is 100% rule-based today.** [`backend/src/magi/memory/l2/episode_formation.py`](../../../backend/src/magi/memory/l2/episode_formation.py) does time-gap clustering + entity-overlap merging + small-set invalidation. No LLM is involved anywhere in episode formation or consolidation. The schema fields `EpisodeWrite.label` and `EpisodeWrite.summary` exist but are unused in production — `create_episode` does not pass them, and `EpisodeConsolidationStats.summaries_generated` is a placeholder counter that is never incremented. This means **we are not "extending" an existing narrative pipeline; we are introducing the first one**.
2. **No `MediaSelector` abstraction exists.** The `photo-library` plugin emits L1 events with photo refs, but "pick a representative photo for this period" has no home. [`docs/unified-asset-resolver-architecture.md`](../../unified-asset-resolver-architecture.md) (status: Proposed) addresses `asset_ref → evidence` resolution but not period-level selection. The redesign needs both halves of the abstraction (selector for hero, resolver for follow-up evidence) — see §New media layer.
3. **`daily_mood_aggregate` does not exist.** `state_bands` are computed per viewport request from L2 assertions + L3 sentiment. A month-scale mood calendar that recomputes 31 days of state per render is unacceptably slow; a small pre-computed projection is required.

### Where each new field lives — period vs episode

A period (day/week/month) contains multiple episodes; episodes are clusters of L1 events. The diary essence is per-period; slice narratives and representative photo are per-episode. The split:

| Layer | New / extended field | Carrier |
|---|---|---|
| **L3 reflection** | `narrative_style: "default" \| "diary_2p"` | new column / variant tag |
| **L3 reflection** | `essence_prose` (string) — period-level 1–3 sentence 2nd-person essence | new column, populated when `narrative_style = "diary_2p"` |
| **L2 episode** | `slice_narrative` (string) — per-episode 1-sentence narrative | new column |
| **L2 episode** | `slice_sensory_detail` (string, optional) — italic detail line | new column |
| **L2 episode** | `magi_standout` (bool) | new column |
| **L2 episode** | `standout_score` (float) | new column |
| **L2 episode** | `standout_reason` (string, optional) — for debugging / hover | new column |
| **L2 episode** | `representative_asset_ref` (string, optional) — cached MediaSelector output | new column |

Already-present and reused as-is: `EpisodeWrite.user_pinned`, `user_label`, `user_note` (per memory-system-design.md §"User feedback and corrections").

The diary generation call writes to L3 (essence) AND each constituent L2 episode (slice narrative + sensory detail) in a single logical transaction. Concrete persistence pattern (single call → fan-out writes vs. atomic batch) is a plan-level decision.

### New LLM scenario: `timeline.diary_narrative`

Registered in [`backend/src/magi/llm/`](../../../backend/src/magi/llm/)'s scenario system. Given a period window's L1 events + L2 episodes + L3 sentiment + place data, it produces:

- `essence_prose` for the period (1–3 sentences, 2nd-person Chinese, see §"Voice and writing" for forbidden patterns)
- For each constituent L2 episode in the period: `slice_narrative` (1 sentence) + optional `slice_sensory_detail` (1 italic sentence)

Scenario routing follows the existing main / summary / cheap model split — model assignment is a user config decision, not hardcoded. Initial recommendation: route to the **main model** by default. This runs once per period generation (not per request), so quality matters more than per-call cost. Users with cost concerns can downgrade in settings.

Generation cadence (plan-level detail):
- End-of-day scheduler job: generate the day's essence + slice narratives for all episodes within that day; compute `daily_mood_aggregate` row
- End-of-week, end-of-month: same shape, broader window
- On-demand fallback: if a user opens a historical period that lacks a generated essence (backfill, edge case), generate sync with loading state

### New media layer: `backend/src/magi/media/`

Lifts media-asset handling out of any single plugin, supporting current `photo-library` and future sources (chat attachments, screen capture, etc.).

```
backend/src/magi/media/
  source_registry.py   # plugins/domains register as media sources (type, query API)
  selector.py          # MediaSelector.pick_representative(start, end, hint)
  resolver.py          # asset_ref → source-specific evidence (per unified-asset-resolver doc)
```

- `MediaSourceRegistry`: photo-library plugin, chat attachment domain, future screen-capture all register here. Each source declares: type identifier, asset-listing query (by time window), and asset-resolution hook.
- `MediaSelector.pick_representative(start, end, hint="hero")` returns an `asset_ref` (or null) representing the period. Selection heuristic considers source priority, content metadata (people-bearing, outdoor, time-of-day fit), and existing user signals (e.g., the asset is already pinned elsewhere). The hint can future-extend ("thumbnail", "moodboard", etc.).
- `AssetResolver` is the implementation slot for [unified-asset-resolver-architecture.md](../../unified-asset-resolver-architecture.md). When that proposal moves from Proposed to implemented, the resolver lives in this same layer; the redesign does not unblock that doc but is compatible with it.

The L2 episode field `representative_asset_ref` is populated by a scheduled job that calls `MediaSelector.pick_representative` for each active or user-pinned episode and caches the result. Timeline viewport reads the cached field; no per-request media selection.

### New projection: `daily_mood_aggregate`

A small read-model table, one row per local day:

```
daily_mood_aggregate(
  day_local_date TEXT PRIMARY KEY,    -- "2026-05-17"
  dominant_valence TEXT,              -- one of: warm, bright, neutral, cool, tense
  volatility_score REAL,              -- 0.0 (flat) – 1.0 (high swings)
  state_curve_compact JSON,           -- hour-by-hour valence values, for sparkline hover
  event_count INTEGER,
  computed_at REAL
)
```

#### Reduction algorithm (Option C from brainstorming)

A day's `dominant_valence` is the valence band that held the **longest time fraction** of the day's active hours (time-weighted, not event-count-weighted — a 3-hour focused session shouldn't be outvoted by 30 quick browser switches).

The cell's **saturation** is driven by `volatility_score`: a day with wide swings (morning tense + afternoon bright) renders fully saturated; a uniform day renders slightly muted. This lets a mixed day stand out from a flat-warm day even though both might have the same dominant color.

On hover, the cell expands a small sparkline of the hour-by-hour valence curve (sourced from `state_curve_compact`) — exposing the dimension that the single-color reduction hides. Peak-end rule was considered and rejected: it conflates "I had peaks today" with "today was peak-feeling overall", which loses too much for a glance-scan widget.

Computation: end-of-day scheduler job (timezone-aware). Re-compute also triggers when late events arrive against a closed day (cursor-driven, not eager polling).

### New endpoints

| Endpoint | Purpose | Owner |
|---|---|---|
| `GET /timeline/standout?month=YYYY-MM` | "值得回来的" list, mixed Magi-curated + user-pinned, date desc | new — backed by L2 episode query WHERE `magi_standout OR user_pinned` |
| `GET /timeline/mood-calendar?month=YYYY-MM` | one row per day: `{date, dominant_valence, volatility, sparkline}` | new — direct read of `daily_mood_aggregate` |

The existing `GET /timeline/viewport` shape gains the new fields described above (essence_prose, per-slice narrative/sensory_detail, hero photo ref, place line). No breaking changes to existing field names.

### Things that get retired

- `TimelineContextDrawer` and all assertion-feedback / episode-annotation handlers in [`Timeline.tsx`](../../../frontend/src/pages/Timeline.tsx) (`handleAssertionFeedback`, `handleAssertionCorrection`, `handleEpisodeAnnotation`).
- `mergeAssertionEvidence` helper. `mergeEpisodeAnnotation` survives but is re-purposed for the ♡ flow with a smaller surface.
- Three-metric bars rendered by `StateBandOverlay` for current-page primary content; `StateBandOverlay` itself can be slimmed to the single 6px band variant.
- The current month-scale `MonthOverviewLane / theme_cards card UI / source_mix panel` (replaced by the new anatomy's themes-row).
- The current 3-line markdown blob at the top of the day view.

### Things that stay

- All sensor ingestion, all L1/L2/L3/L4 stores, all clustering/insight pipelines.
- `forgetEpisode(id, false)` API surface, called from the new ⋯ menu.
- `annotateEpisode` API surface, called from the new ♡ flow.
- Hour-scale `clusters` and `raw_events` (rendered differently in detective mode).
- L2 episode rule-based formation pipeline (the new narrative pipeline runs **after** episode formation/consolidation; it does not replace it).

## Risks and open questions

1. **Quality of generated 2nd-person prose.** This is the highest-risk piece. Bad prose ("你今天浏览了 Chrome 14 次") destroys the entire concept. Mitigation: invest in the L3/overview prompt with concrete few-shots, evaluate generated output on real user days before launch, fall back to a terse rule-based summary on generation failure.
2. **Photo privacy.** Pulling photos from the user's library and showing them as hero requires (a) clear permission UX (lives outside this spec, in the photo-library plugin's settings), (b) graceful "this photo seems sensitive, show fallback" affordance later. v1 trusts plugin permissions; user can remove specific photos from the timeline via the ⋯ menu.
3. **Photo resolution / loading performance.** Hero images need to be served at a reasonable resolution (~1600px wide). The gateway should serve from the local file index, not re-encode. Existing attachment-resource pipeline is the closest analogue; a thin "photo serving" route may be needed.
4. **Mood calendar color stability.** State bands are computed per viewport (per architecture doc), so color drift between days is possible. Mitigation: compute mood-calendar colors from a daily-aggregated cache, not on-the-fly per cell.
5. **"值得回来的" first-experience seed.** The "你今天第一次打开 Magi" seed must come from somewhere — either a hardcoded onboarding event or a real timeline event with a special marker. Recommendation: emit a real `onboarding_complete` timeline event on first run.
6. **Hour view discoverability.** Users who land on day and want raw events have to click the "时" toggle. Acceptable, but should be visually obvious.

## Acceptance criteria

1. Opening `/timeline` with any sensor data lands on the latest complete day, with hero + state band + themes + slices rendered.
2. A day with photos shows a real photo as hero; a day without shows the warm gradient fallback.
3. The sidebar mood calendar fills cells for days that have any event data, with mood-derived color.
4. The "值得回来的" sidebar list is non-empty as long as Magi has any auto-curation candidates, with seed behavior on Day 1.
5. Hovering a slice reveals ♡; clicking adds the underlying episode to "值得回来的" via existing annotate API; sidebar reflects the change.
6. Hovering a slice reveals ⋯; menu "不算这天的样子" calls `forgetEpisode(id, false)` and removes the slice from the current view with a 4s undo affordance.
7. Hour scale renders a flat clustered list with no hero, no themes, no ♡, no ⋯ menu, no drawer.
8. No metric percentages, no internal IDs, and no markdown literals appear anywhere on the page.
9. `TimelineContextDrawer` is removed from the page; no right-drawer affordance exists.
10. Default landing scale is `day`.

## Where to put more detail

Detailed component-by-component implementation steps, prompt templates, and migration strategy belong in the implementation plan (next step), not this spec. The plan will likely decompose this into phases (frontend shell first, then photo integration, then Magi-auto-curation, then prose generation) — that decomposition is the plan author's call.
