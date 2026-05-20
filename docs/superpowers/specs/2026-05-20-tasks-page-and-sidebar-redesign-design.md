# Tasks Page & Sidebar Redesign

**Date:** 2026-05-20
**Status:** Approved (brainstorming)
**Author:** asuka + Claude

## Background

Three pain points on the current Tasks experience:

1. The sidebar `tasks` panel is an empty container ([Sidebar.tsx:548-554](../../../frontend/src/components/layout/Sidebar.tsx)). Only `conversation` / `timeline` / `memory` have populated side panels.
2. Inside the Tasks page itself, a top-level `<Tabs>` toggles between **background tasks** and **scheduled tasks**, and within "scheduled" two distinct concerns (configuration + runtime activity) are stacked on one page.
3. Schedule configuration is not discoverable: no filter, no way to see disabled schedules, no "create" entry point, and a fixed ±1h activity window that hides historical runs.

## Goals

- Move the in-page tab toggle into the sidebar (turning the empty panel into a real navigation surface).
- Split the scheduled experience into two independent sub-pages: **configuration** and **execution history**.
- Add filters, status visibility, and a create flow to the configuration page.
- Make the activity history view first-class: time window control, longer windows than ±1h.
- Keep the change surgical — no unrelated refactor.

## Non-goals (deferred)

- Name / prompt full-text search.
- Slash-command create entry point (e.g. `/schedule …` in chat composer).
- Any new `target_type` (still only `USER_AGENT_TASK` is user-creatable).

## Discovery / current-state notes

### `ScheduledTargetType` enum ([backend/src/magi/scheduler/contracts.py:13](../../../backend/src/magi/scheduler/contracts.py))

| Value | Family |
|---|---|
| `USER_AGENT_TASK` | User-defined (prompt) — **only editable kind** |
| `SENSOR_SYNC` | Sensor sync (per plugin) |
| `MEMORY_L2_MAINTENANCE` / `MEMORY_L3_SUMMARY` / `MEMORY_L4_MAINTENANCE` | Memory maintenance |
| `TIMELINE_DIARY_NARRATIVE` / `TIMELINE_STANDOUT_RESCORE` / `TIMELINE_MOOD_AGGREGATE` / `TIMELINE_REPRESENTATIVE_ASSET` | Timeline maintenance |

### Backend API state

- `GET /schedules` — already accepts `enabled_only=true|false` query (default **false**). Frontend currently hard-codes `true`, hiding disabled.
- `POST /schedules` — accepts a full `ScheduleDefinition` body. For our purposes the body forces `target_type=USER_AGENT_TASK`, generates `schedule_id`, sets `target_payload.prompt`, etc.
- `GET /schedules/activity` — **does not** read the historical `schedule_executions` table. It only returns queued/running sensor jobs + currently running non-sensor states + upcoming `next_run_at` entries. The `execution_repository.list_executions(...)` historical method exists but is unused by the HTTP API.
- `POST /schedules/{id}/run`, `PATCH /schedules/{id}`, `DELETE /schedules/{id}` — exist, work for `USER_AGENT_TASK` (others are management-locked).

## Decisions

### Information architecture

**Sidebar Tasks panel** becomes a pure nav list (parallel to `MemoryPanel`):

```
┌── 任务 ────────────────────┐
│ ▸ 后台任务         [3]    │  ← activeBackgroundCount
│ ▸ 调度配置                │
│ ▸ 调度记录         [1]    │  ← currently-running schedule count
└────────────────────────────┘
```

The activity-bar `tasks` icon's badge becomes `activeBackgroundCount + runningSchedulesCount` (merged), so the icon still surfaces "something needs my attention".

**Routes:**

| Before | After |
|---|---|
| `/tasks` + `?tab=background` (default) | `/tasks/background` (default) |
| `/tasks?tab=scheduled` | `/tasks/schedules` (configuration) |
| — | `/tasks/schedules/activity` (history) |
| `/tasks?taskId=…` | preserved as redirect into `/tasks/background` with the same query param |

Existing `?tab=` query reads auto-redirect to the new path on mount.

**Page shell.** The current `<Tabs>` inside [Tasks.tsx](../../../frontend/src/pages/Tasks.tsx) is removed. The header (title + refresh button) is extracted into a shared `TasksPageFrame` layout component, structurally parallel to [MemoryPageFrame.tsx](../../../frontend/src/pages/memory-pages/MemoryPageFrame.tsx). Each of the 3 sub-pages is its own lazy-loaded route module.

### Background Tasks page (`/tasks/background`)

Mostly unchanged from current `background` tab content (sectioned: running / queued / finished, with pagination + drawer).

Additive only: each `TaskRow` shows an optional **source chip** (`来源：调度 · <name>`) when the task originated from a schedule. Pulled from a new optional `source_schedule_id` field on the background task DTO. Clicking the chip navigates to `/tasks/schedules?highlight=<schedule_id>` (highlights the row in the config table).

> Backend dependency: `source_schedule_id` on `BackgroundTaskDTO`. If not available this iteration, ship the UI with the chip hidden (read the field but render nothing when absent). No frontend-visible regression.

### Schedule Configuration page (`/tasks/schedules`)

**Header:**

- Title + refresh button (consistent with frame).
- Right-aligned primary button: **`+ 新建调度任务`**.

**Filter bar:**

- Top row: segmented chip group.
  - `全部` | `用户自定义` | `传感器同步` | `记忆维护` | `时间线维护`
  - Each chip shows a count badge (live).
- Right-aligned: toggle **`显示已禁用`** (default **off**).

Category mapping (one place, exported helper):

```ts
function scheduleCategory(target_type: ScheduledTargetType): Category {
  if (target_type === 'user_agent_task') return 'user';
  if (target_type === 'sensor_sync') return 'sensor';
  if (target_type.startsWith('memory_')) return 'memory';
  if (target_type.startsWith('timeline_')) return 'timeline';
  return 'other';
}
```

**Table columns:**

| Column | Notes |
|---|---|
| 名称 / 类型 | Title, plus a small badge for `运行中` (target_state.running) or `已禁用` (when `!enabled` and toggle is on). |
| 规则 | `<triggerType> <summary>` (existing helper). |
| 上次运行 | `target_state.last_run_at`. |
| 下次运行 | `target_state.next_run_at`. |
| 操作 | See below. |

**Action column variants:**

- **User schedule** (`USER_AGENT_TASK`): `运行` · `编辑` · `启停` · `删除`.
- **Sensor schedule** (`SENSOR_SYNC`): `运行` · `⚙ 打开插件设置` · `启停`. (uses existing `settings_link`)
- **Memory / Timeline system schedule**: `运行` · `ⓘ 说明` · `启停`. Edit/delete not available.

**Sensor grouping.** When the active chip is `传感器同步`, rows are grouped by `plugin_id` (a header row per plugin showing plugin name + icon, derived from existing plugin manifest). Under other chips, the table is flat.

**Empty states:**

- `用户自定义` chip selected with no rows → centered empty-state card with CTA "**+ 创建你的第一个调度任务**".
- Any other chip empty → small inline `—` placeholder row.

### Schedule History page (`/tasks/schedules/activity`)

**Header:**

- Title + refresh.
- Time window segmented: **`今天` | `近 24 小时` | `近 7 天`** (default `今天`).
- Optional category chip row mirroring the config page (`全部` plus the 4 families).
- Optional status filter: `全部` | `运行中` | `成功` | `失败` | `已取消` | `队列中`.

**Table columns:** name / status / planned_at / started_at / duration / actions.

**Actions:**

- `停止` — when `activity.cancellable`.
- `跳转后台任务详情` — only when activity has a `background_task_id` (USER_AGENT_TASK activities). Behind backend availability; hide when absent.

**Pagination.** Server-side `since` / `until` + `limit` (≤ 100). Cursor-style optional but offset is fine for v1.

### Drawers

**ScheduleEditDrawer** (existing) is extended to accept a `mode: 'create' | 'edit'`.

- `create` mode:
  - Hide schedule_id row.
  - Add a `名称` (display name) input — required, persisted as `metadata.display_name`.
  - `target_type` is fixed `USER_AGENT_TASK`; not user-selectable.
  - Prompt + trigger + enabled fields identical to edit.
  - Save calls `schedulesApi.create(...)`.
- `edit` mode: unchanged behavior.

**ScheduleInfoDrawer** (new) — opens from the ⓘ button on memory / timeline system schedules.

- Sections:
  - Title (i18n-driven friendly name) + a paragraph description.
  - Read-only block: current trigger summary, next_run_at, last_run_at, last_error.
  - Action row: `立即运行` · `启停` (mirrors the table-row actions for parity).
- i18n keys: `tasks.scheduled.systemJobs.<target_type>.title` and `…description`. One entry per memory/timeline `target_type` (7 entries).

### Sidebar changes

- `Sidebar.tsx::renderPanelContent` adds a `tasks` branch (today it falls through to the empty placeholder).
- New helper `renderTasksPanel` mirrors `renderMemoryPanel`: 3 nav buttons → 3 routes.
- The activity icon badge becomes `activeBackgroundCount + runningSchedulesCount`. Add a small `useRunningSchedulesCount` selector (zustand store or derived from a lightweight polled query — see "Data layer").

### Data layer

**Frontend store additions:**

- New zustand slice `useSchedulesStore` (or extend an existing one) holding: `schedules`, `categoryCounts`, `runningCount`. Hydrated by the config page; the sidebar subscribes to `runningCount` for the badge.

**API client changes** ([frontend/src/api/modules/schedules.ts](../../../frontend/src/api/modules/schedules.ts)):

- `list({ enabledOnly?: boolean })` → already in shape; new caller passes `enabledOnly: false` when "显示已禁用" toggle is on (default true).
- `listActivity({ since?: number; until?: number; limit?: number; statuses?: string[]; targetTypes?: string[] })` — new parameters.
- `create(body)` — new method. Body shape:
  ```ts
  {
    schedule_id: string;        // generated client-side: `user-${nanoid()}`
    target_type: 'user_agent_task';
    target_key: string;         // same as schedule_id for v1
    trigger: TriggerDefinition;
    target_payload: { prompt: string };
    metadata: { display_name: string };
    enabled: boolean;
  }
  ```
- (existing) `update`, `remove`, `run`, `cancelActivity` unchanged.

**Backend changes required:**

1. **`GET /schedules/activity`** must read `schedule_executions` table:
   - Accept `since`, `until`, `limit`, `statuses[]`, `target_types[]` query params.
   - Merge: outstanding sensor jobs (current behavior) + execution history rows + currently-running non-sensor schedules + upcoming `next_run_at` previews.
   - Map execution table columns into the existing `ScheduleActivityDTO` shape; status mapping: `success → succeeded`, `failure → failed`, plus `running`, `queued`, `upcoming`, `cancelled`.
   - Default window: last 24 hours if no `since`/`until` provided.
   - This is the largest backend ticket.

2. **`ScheduleActivityDTO` (optional, P1)**: optional `background_task_id` for activities backed by a `USER_AGENT_TASK` execution that spawned a background task. If a join is straightforward via the execution row's metadata, do it; otherwise punt to a follow-up.

3. **`BackgroundTaskDTO` (optional, P1)**: optional `source_schedule_id`. Set by the executor that spawns the task from a `USER_AGENT_TASK` schedule fire. If not available this iteration, ship `null` and the UI hides the chip.

If items 2 + 3 are not feasible in this iteration, hide the cross-link UI behind a presence check and leave a TODO comment with the field name expected. No follow-up tracking ticket is required from the design doc itself.

### i18n additions (zh-CN + en)

- `shell.tasks.background` / `shell.tasks.schedules` / `shell.tasks.activity`
- `tasks.scheduled.categories.{all, user, sensor, memory, timeline}`
- `tasks.scheduled.filters.showDisabled`
- `tasks.scheduled.filters.window.{today, last24h, last7d}`
- `tasks.scheduled.actions.{create, openInfo, viewBackgroundTask}`
- `tasks.scheduled.empty.userCta`
- `tasks.scheduled.systemJobs.<target_type>.title` / `…description` (7 entries)
- `tasks.scheduled.status.{running, queued, upcoming, succeeded, failed, cancelled}` (some already exist; reconcile)

## Testing

- Split existing `tasksPage.test.tsx` into three new specs (`backgroundPage`, `schedulesConfigPage`, `schedulesActivityPage`).
- New tests:
  - Category chip switching filters rows + count badges.
  - `显示已禁用` toggle reveals disabled rows.
  - Sensor chip groups rows by plugin.
  - Create drawer submits with display_name + prompt and calls `schedulesApi.create`.
  - Info drawer renders friendly name from i18n.
  - Activity page time window selector triggers re-fetch with `since`.
  - Sidebar badge sums background + running schedules.

## Out of scope (explicitly)

- Renaming `schedule_id` shape or migration. Stays as-is.
- Backend cross-link fields (`source_schedule_id`, `background_task_id`) are nice-to-have; the frontend tolerates their absence.

## Open questions / risks

- The `target_state.running` flag for non-sensor schedules — when is it set/cleared today? Need to confirm it correctly tracks single-shot execution so the activity page's "currently running" row stays accurate.
- For sensor schedules grouped by plugin: the plugin display-name / icon source. Reuse whatever `Settings → Timeline` already shows. Confirm during implementation.
