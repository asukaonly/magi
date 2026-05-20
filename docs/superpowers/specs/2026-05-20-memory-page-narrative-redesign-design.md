# Memory Page Narrative Redesign — Design Spec

Date: 2026-05-20
Status: Draft, awaiting plan
Scope: `frontend/src/pages/memory-pages/` + minimal backend extensions for non-session portrait

## Background

The current memory page is a developer-facing surface. The sidebar exposes the storage layers verbatim (`工作台记忆 / 事件记忆 / 知识记忆 / 摘要反思记忆 / 工具技能记忆` ≈ L0/L1/L2/L3/L4), and the landing page is a search workbench with database statistics ("3,001 条记忆 / 42 MB") and a query-mode dropdown with names like `event_stream`, `exact_fact`, `episode_recall`.

End users do not have a mental model of L0–L4. They have a mental model of "what does Magi remember about me, and what does it think about me."

The timeline page is already the place to read **time** ("what happened on this day"). The memory page should not be a second timeline. It should be the place to read **the AI's interpretation of you** — the curated, synthesized, reviewable narrative.

This redesign converts the memory page from a layer-typed admin surface into a **focused reading surface for Magi-woven narrative**, while reusing existing memory infrastructure rather than introducing new memory primitives.

## Product Principles

1. **Memory page subject = "you"**, not "events", not "the database". Time-axis browsing belongs to the timeline page.
2. **Storage layers are invisible by default.** L0/L1/L2/L3/L4 are vocabulary for the engineering team, not for the UI. The L1 event explorer and L4 procedural memory remain reachable via a developer view, but are not top-level.
3. **Magi has opinions, with humility.** Insights are framed as "I noticed…", every claim shows evidence, and every claim is reviewable (confirm / reject / annotate).
4. **One activity per surface.** The landing surface is the narrative arc reader. Recall search, portrait, raw episodes, and governance each live in their own view via sidebar navigation. No multi-panel dashboard.
5. **Build on what already exists.** Narrative arcs are presented L3 insights + L3 temporal summaries — no new memory schema. Episodes are existing L2 records.

## Boundary vs. Timeline Page

| | Timeline page | Memory page |
|---|---|---|
| Subject | Time | You |
| Primary axis | Calendar (day/week/month) | Narrative thread, person, place, topic |
| Tone | Immersive, river-like, continuous | Reflective, book-like, curated |
| Data primary | L1 events + transient clusters + L2 episodes for clustering | L3 insights + L3 temporal summaries + L2 episodes/entities + portrait projection |
| Read pattern | Scroll a window of time | Read an arc, drill into its episodes, drill into its events |

The two pages share data — L2 episodes appear in both — but with different framing. An episode in the timeline is a marker on a date; the same episode in memory is a chapter inside a named arc.

## Sidebar

Five top-level items. No L-named items.

```
🌀  故事     (default landing)
📔  章节
🪞  画像
🔍  回忆
⚙️   治理
```

The existing developer-only entries (working memory, raw L1 events, raw L4 procedures) move under 治理 → "开发者视图" rather than disappearing.

## View 1 — 故事 (Stories, default landing)

The landing surface. Reads as "Magi's recent reflections about you," presented as a feed of narrative cards.

### Card sources

Every story card is one of these existing backend records, presented with consistent product framing:

- **Insight cards** — L3 `insight`-typed summaries produced by [state_change_service.py](../backend/src/magi/memory/l3/state_change_service.py), [contradiction_service.py](../backend/src/magi/memory/l3/contradiction_service.py), [trend_shift_service.py](../backend/src/magi/memory/l3/trend_shift_service.py), and [task_reflection_service.py](../backend/src/magi/memory/l3/task_reflection_service.py). Each already carries `insight_key`, `review_state`, `insight_metadata`, and evidence references.
- **Temporal arc cards** — L3 `temporal` summaries with `day`, `week`, `month` windows, when they materially differ from the previous same-period summary. Hour summaries are excluded from this feed; they are recall material.

### Card shape

Each card shows:

- **Title** — for insights, the rendered insight headline; for temporal summaries, a "本周 / 本月 / 5 月 14–20 日 这段时间" framing.
- **Lede** — 1–2 sentences from the insight content or the `change_and_pattern.timeline` field of a temporal summary.
- **Evidence chip** — "N 条证据"; opens a side drawer listing constituent L1 / L2 records with backlinks.
- **State chip** — derived from `review_state`: `proposed` / `confirmed` / `rejected` / `archived`. Proposed cards show a subtle dot.
- **Time anchor** — when the insight or summary's coverage window ended.
- **Quick actions** — 确认 / 拒绝 / 备注 / 收起. Confirm and reject update `review_state` via existing user-feedback APIs.

### Order

- Default sort: `coverage_end_ts DESC`, with `proposed` cards interleaved at the top for the first three positions if any exist.
- Confirmed and rejected cards remain in the feed but visually quieted.
- An "已收起" group at the bottom (collapsed by default) holds dismissed cards for later un-collapse.

### Empty state

When no insights or temporal summaries exist yet:

- A single-paragraph empty card: "Magi 还没有得出关于你的反思。继续使用一段时间，这里会出现它对你的观察。"
- Link to 回忆 view as a fallback action.

### Drill-down

Clicking the title opens an arc detail in a right-rail panel that overlays the feed without leaving the view. The detail panel shows:

- Full insight content (`summary_content`).
- Constituent evidence list grouped by source — episodes, individual L1 events, related assertions/edges.
- "上一次同主题反思" link when `insight_key` repeats (via the recurring insight upsert behavior described in [memory-system-design.md:588](../memory-system-design.md)).
- Annotation field (free text) — saves to `insight_metadata.user_note`.

### What is explicitly NOT in the 故事 view

- No "search box" on this surface (search lives in 回忆).
- No global stats (total memories, disk usage). Those move to 治理.
- No layer-named badges (`L1` / `L2` / `L3`). Cards carry product-level chips only.

## View 2 — 章节 (Episodes)

A pure, browsable list of L2 episodes — the raw curated chapters that constitute the user's experience.

### Data source

`l2_cognition_store` → `episodes` table. Existing columns `user_label`, `user_note`, `user_pinned`, `episode_type`, `primary_entity_ids`, `primary_place_ids`, `primary_topic_keys`, `dominant_mode`, `started_at`, `ended_at`, `summary`.

### List shape

- Top section: `user_pinned = true` episodes, persistent.
- Below: paginated reverse chronological list of `status = 'active'` episodes.
- Filter chips: by type (`activity / visit / session / conversation`), by mode (`dominant_mode`), by entity (multi-select from `primary_entity_ids`).
- Each row shows: title (prefer `user_label`, fall back to `label`, fall back to `summary[:80]`), episode type, time range, primary entity chips, pinned star, user note presence indicator.

### Episode detail

A detail panel with:

- Editable `user_label` and `user_note`.
- Toggle for `user_pinned`.
- Member events list (`episode_events`) with timestamps.
- "Forget this episode" action — calls existing `forget_episode`.

### What is explicitly NOT in 章节

- No automatic clustering UI here; clustering lives in the timeline. 章节 shows L2 episodes as user-touchable atomic units.

## View 3 — 画像 (Portrait)

The synthesized "Magi's read of you." Replaces the per-session portrait rail with a global, persistent view.

### Data sources

- `user_profile_projection` in `memory.db` — product-facing read model for the local user profile.
- L2 ToM snapshots — periodically refreshed entity portraits.
- L2 assertions with `entity_id = self_user` (or equivalent), grouped by `memory_subdomain`.
- L2 knowledge graph edges where the user is subject, for the "relationships" segment.

### Backend addition (small)

The existing `/memory/portrait` endpoint is session-scoped (parameters `session_id`, `user_id`). The Portrait view needs a non-session variant.

Proposed minimal extension:

- Add a `/memory/portrait/self` endpoint (or accept `session_id=null` on the existing endpoint) that returns observations sourced from `user_profile_projection` + L2 ToM snapshot for the user, **not** from the current chat session.
- Response shape mirrors `PortraitPayload` so the frontend can reuse the same display components.

This is the only new backend work in this redesign.

### Layout

A single-column reading layout with named segments:

1. **身份** — name, addressing preference, identity facts from `identity_profile` assertions.
2. **当下** — recent state assertions (`memory_subdomain = 'state'`): mood band, focus mode, energy.
3. **偏好** — stable preferences from `stable_preference` edges and `communication_profile` assertions.
4. **关系** — top-confidence entity edges grouped by predicate: 在意的人 / 用的工具 / 去的地方.
5. **Magi 对你的总体印象** — the latest ToM snapshot's `core_traits` paragraph, when present.

### Reviewability

Each segment item carries the same confirm / reject / correct controls used in 故事 cards, wired to the same user-agency APIs (`apply_user_feedback`, `correct_assertion`, `reject_edge`).

### Empty / cold-start

Reuse the existing `ColdStartReason` machinery from [memoryPortrait.ts](../frontend/src/api/modules/memoryPortrait.ts) — when there are no observations yet, show the same cold-start line currently produced by the backend, plus a hint that the portrait grows with use.

## View 4 — 回忆 (Recall)

A direct evolution of the current "Memory Workbench" search, with consumer-facing labels.

### What changes from current workbench

- Removes top header stats (`记忆条数 / 占用大小`).
- Removes raw layer badges in result cards. Results render with product-facing kind labels only.
- Renames query modes:

| Current internal name | UI label |
|---|---|
| `auto` | 智能 |
| `event_stream` | 你说过 / 做过的事 |
| `exact_fact` | 一句具体的事实 |
| `current_state` | 你现在的状态 |
| `episode_recall` | 一段经历 |
| `summary` | Magi 的总结 |
| `strategy` | Magi 学到的做事方式 |

- The diagnostics panel ("requested mode / resolved mode / executed layers") is hidden by default and lives under a "调试细节" disclosure for developers.

### What does NOT change

- The underlying retrieval pipeline (`HybridRetrievalService`, mode registry, RRF, evidence assemblers) is untouched.
- The 9-mode contract on `memory_query` is untouched.

## View 5 — 治理 (Governance)

The user-agency surface, plus the home for previously top-level developer affordances.

### Sections

1. **待审阅** — pending L3 insight cards with `review_state = 'proposed'`, queued for batch confirm/reject. Driven by the same query that backs the 故事 view, filtered to proposed-only.
2. **修正过的事实** — list of corrected assertions (with old → new) and rejected edges, with the option to un-reject.
3. **遗忘** — entity-level and time-range forget controls, calling `forget_entity` / `forget_time_range` / `forget_episode`.
4. **隐私范围** — per-source `privacy_scope` settings (read-only audit + edit where applicable).
5. **开发者视图** (collapsible) — replaces the current dev-style sidebar items:
   - 工作台记忆 (L0) — read-only
   - 原始事件 (L1) — the existing L1 event explorer page is kept here for power users
   - 工具技能记忆 (L4) — kept here for power users
   - 存储统计 — total memories and disk usage moved here

## What's NOT in scope for this redesign

These are deliberately deferred:

- A new "narrative arc" data structure spanning multiple L3 insights. The 故事 view ships using existing L3 records; if cross-insight arcs are needed later, that becomes a separate design.
- Person / place / topic "卷宗" pages (per-entity biography view). The portrait covers the user; per-entity biographies are a future extension.
- Any change to the underlying memory schema, ingestion pipeline, retrieval pipeline, or query modes.
- Re-design of the timeline page or its data sources.

## Data Source Summary

| View | Existing backend used | New backend needed |
|---|---|---|
| 故事 | L3 `summary_store` (insight + temporal summary listing, filtered by `summary_type` and time window); existing user-feedback APIs | Likely a thin list endpoint exposing review state and evidence refs in one payload — currently per-type endpoints exist; a unified "story feed" endpoint reduces frontend joins. |
| 章节 | L2 `episodes` CRUD; `forget_episode` | None. May need a list endpoint with filter + pin-first ordering if not already present. |
| 画像 | `user_profile_projection`; L2 ToM snapshot; L2 assertions; KG edges; `apply_user_feedback`, `correct_assertion`, `reject_edge` | `/memory/portrait/self` (or session-less variant of `/memory/portrait`) returning the same `PortraitPayload` shape, sourced from user_profile_projection + ToM snapshot. |
| 回忆 | `HybridRetrievalService` / mode registry / 9-mode `memory_query`; existing search results endpoint | None. UI-only changes (labels, hidden diagnostics). |
| 治理 | All user-agency APIs already enumerated in memory-system-design.md; existing L1 / L4 / stats pages and endpoints | None. |

## Risk and Open Questions

1. **Insight quality drives the entire 故事 view.** If L3 insight generation is sparse or noisy, the landing page is sparse or noisy. Before shipping, run the insight pipeline against the current local DB and judge whether the proposed-card stream looks readable to a real user, not just to a developer. If it does not, the empty state and temporal-summary fallback must do real work, and we may want a "本周回顾" first card seeded from the most recent week temporal summary even when no insights exist.
2. **Story-feed endpoint shape.** The cleanest UI fetch is one paginated, time-sorted, multi-type story feed. Today the frontend would need to fan out to multiple summary-type endpoints. The plan should clarify whether to add a unified endpoint or do the join in the frontend for v1.
3. **Per-card actions and write paths.** The frontend already calls some user-agency APIs (assertion confirm/reject for example). The redesign assumes those endpoints are reachable from the new card UIs. The plan should enumerate each action → endpoint pair.
4. **Localization.** Every new product-facing label needs zh / en pairs. The current memory page uses the `app` namespace; the redesign keeps that namespace but introduces a new `memory.story.*`, `memory.episodes.*`, `memory.portrait.*`, `memory.recall.*`, `memory.governance.*` subtree.
5. **Tests.** Existing tests reference the current page structure (e.g. `memoryEventsPageSearch.test.tsx`, `useMemoryInitialLoadScope.test.tsx`). The plan must update or replace these; routes for the removed top-level layer pages need redirects or graceful fallbacks.

## Deliverable shape (what the implementation plan must produce)

- Replace `MemoryOverviewPage` with a `MemoryStoryPage` that owns the 故事 feed.
- Keep `MemoryEventsPage` (L1) but move its sidebar entry under 治理 → 开发者视图.
- Replace the current `L0Tab`, `L4Tab` sidebar entries with the same demotion (under 开发者视图).
- Promote per-session portrait UI (`memoryPortrait.ts` consumers) to a global Portrait view via the new endpoint variant.
- Refactor the sidebar component to render the five-item taxonomy with the developer subtree collapsible.
- Update i18n keys for the new taxonomy.
- Add or update tests to cover: story feed ordering with mixed insight/temporal cards, episode pinning, portrait cold-start vs. populated, recall view rename of modes, governance review-queue flow.
