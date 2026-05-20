# Tasks Page & Sidebar Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [docs/superpowers/specs/2026-05-20-tasks-page-and-sidebar-redesign-design.md](../specs/2026-05-20-tasks-page-and-sidebar-redesign-design.md)

**Goal:** Replace the monolithic Tasks page with three sub-pages (`后台任务`, `调度配置`, `调度记录`) navigated from the sidebar panel; add category filters, create flow, system-job info drawer, and a real history view backed by `schedule_executions`.

**Architecture:** Mirror the `memory-pages/` pattern: barrel-exported lazy pages sharing a `TasksPageFrame`. Sidebar adds a `renderTasksPanel` branch parallel to `renderMemoryPanel`. Backend `GET /schedules/activity` is extended to read the `schedule_executions` table and accept `since` / `until` / `target_types` / `statuses` query params.

**Tech Stack:** React 18 + TypeScript + Vite + Vitest + Testing Library, Tailwind/shadcn (existing), Zustand, react-router-dom v6, FastAPI + aiosqlite (backend), pytest-asyncio.

---

## File Structure

**New frontend files:**

```
frontend/src/pages/tasks-pages/
├── index.ts
├── TasksPageFrame.tsx
├── BackgroundTasksPage.tsx
├── ScheduleConfigPage.tsx
├── ScheduleActivityPage.tsx
├── components/
│   ├── BackgroundTaskRow.tsx
│   ├── BackgroundTaskDetailDrawer.tsx
│   ├── ScheduleEditDrawer.tsx
│   ├── ScheduleInfoDrawer.tsx
│   ├── ScheduleConfigTable.tsx
│   ├── ScheduleActivityTable.tsx
│   ├── CategoryChipBar.tsx
│   ├── IconActionButton.tsx
│   └── TasksPaginationBar.tsx
└── utils/
    ├── scheduleCategory.ts
    ├── scheduleHelpers.ts
    └── scheduleFormatters.ts
```

**Modified files:**

- `frontend/src/pages/Tasks.tsx` — deleted.
- `frontend/src/router/index.tsx` — new routes + legacy redirect.
- `frontend/src/components/layout/Sidebar.tsx` — `renderTasksPanel` + badge.
- `frontend/src/api/modules/schedules.ts` — `create()`, expanded `listActivity()`, expanded DTOs.
- `frontend/src/stores/schedules.ts` *(new)* — running-schedules count selector.
- `frontend/src/i18n/locales/{zh-CN,en}/app.json` — new keys.
- `frontend/src/__tests__/tasksPage.test.tsx` → split into `backgroundTasksPage.test.tsx` / `scheduleConfigPage.test.tsx` / `scheduleActivityPage.test.tsx`.

**Backend files modified:**

- `backend/src/magi/scheduler/execution_repository.py` — new `list_executions_filtered` method.
- `backend/src/magi/api/routers/schedules.py` — extended `list_schedule_activity` handler.
- `backend/tests/scheduler/test_execution_repository.py` *(may exist; see Task 5)* — tests for the new helper.
- `backend/tests/api/test_schedules_activity.py` *(new)* — HTTP-level test.

---

## Phase 1 — Foundation utilities

These small modules are dependencies for every later page. Build them first.

### Task 1: Category mapping helper

**Files:**
- Create: `frontend/src/pages/tasks-pages/utils/scheduleCategory.ts`
- Test: `frontend/src/__tests__/scheduleCategory.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/scheduleCategory.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { scheduleCategory } from '@/pages/tasks-pages/utils/scheduleCategory';

describe('scheduleCategory', () => {
  it('maps user_agent_task to user', () => {
    expect(scheduleCategory('user_agent_task')).toBe('user');
  });
  it('maps sensor_sync to sensor', () => {
    expect(scheduleCategory('sensor_sync')).toBe('sensor');
  });
  it.each([
    'memory_l2_maintenance',
    'memory_l3_summary',
    'memory_l4_maintenance',
  ])('maps %s to memory', (value) => {
    expect(scheduleCategory(value)).toBe('memory');
  });
  it.each([
    'timeline_diary_narrative',
    'timeline_standout_rescore',
    'timeline_mood_aggregate',
    'timeline_representative_asset',
  ])('maps %s to timeline', (value) => {
    expect(scheduleCategory(value)).toBe('timeline');
  });
  it('falls back to other for unknown values', () => {
    expect(scheduleCategory('weird_new_type')).toBe('other');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/__tests__/scheduleCategory.test.ts
```

Expected: FAIL — `Cannot find module '@/pages/tasks-pages/utils/scheduleCategory'`.

- [ ] **Step 3: Implement**

`frontend/src/pages/tasks-pages/utils/scheduleCategory.ts`:

```ts
export type ScheduleCategory = 'user' | 'sensor' | 'memory' | 'timeline' | 'other';

export const SCHEDULE_CATEGORIES: ReadonlyArray<ScheduleCategory> = [
  'user',
  'sensor',
  'memory',
  'timeline',
] as const;

export function scheduleCategory(targetType: string): ScheduleCategory {
  if (targetType === 'user_agent_task') return 'user';
  if (targetType === 'sensor_sync') return 'sensor';
  if (targetType.startsWith('memory_')) return 'memory';
  if (targetType.startsWith('timeline_')) return 'timeline';
  return 'other';
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/__tests__/scheduleCategory.test.ts
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/tasks-pages/utils/scheduleCategory.ts \
        frontend/src/__tests__/scheduleCategory.test.ts
git commit -m "feat(tasks): add scheduleCategory helper"
```

---

### Task 2: Extract schedule helpers and formatters

**Files:**
- Create: `frontend/src/pages/tasks-pages/utils/scheduleHelpers.ts`
- Create: `frontend/src/pages/tasks-pages/utils/scheduleFormatters.ts`

These hold the helper functions currently inline in `Tasks.tsx` (lines 80–278). Moving them now lets the new pages import without duplicating.

- [ ] **Step 1: Create `scheduleFormatters.ts`**

`frontend/src/pages/tasks-pages/utils/scheduleFormatters.ts`:

```ts
import type { ScheduleDTO } from '@/api';

export const formatUnixSeconds = (ts: number | null | undefined): string => {
  if (!ts || !Number.isFinite(ts)) return '—';
  return new Date(ts * 1000).toLocaleString();
};

export const formatScheduleTableTime = (ts: number | null | undefined): string => {
  if (!ts || !Number.isFinite(ts)) return '—';
  return new Intl.DateTimeFormat(undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(ts * 1000));
};

export const formatDuration = (durationMs: number | null | undefined): string => {
  if (!durationMs || !Number.isFinite(durationMs)) return '—';
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
};

export const toFiniteNumber = (value: unknown): number | null => {
  const next = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(next) ? next : null;
};

const formatCompactInterval = (seconds: number): string => {
  const remainingStart = Math.max(1, Math.round(seconds));
  const units = [
    ['d', 24 * 60 * 60],
    ['h', 60 * 60],
    ['m', 60],
    ['s', 1],
  ] as const;
  let remaining = remainingStart;
  const parts: string[] = [];
  for (const [suffix, unitSeconds] of units) {
    if (remaining < unitSeconds) continue;
    const value = Math.floor(remaining / unitSeconds);
    remaining %= unitSeconds;
    parts.push(`${value}${suffix}`);
    if (parts.length === 2) break;
  }
  return parts.length > 0 ? parts.join(' ') : `${remainingStart}s`;
};

const toScheduleToken = (value: unknown, fallback: string = '*'): string => {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text ? text : fallback;
};

const formatCronExpression = (config: Record<string, unknown>): string => (
  [
    toScheduleToken(config.second, '0'),
    toScheduleToken(config.minute),
    toScheduleToken(config.hour),
    toScheduleToken(config.day),
    toScheduleToken(config.month),
    toScheduleToken(config.day_of_week),
  ].join(' ')
);

export const getScheduleTriggerSummary = (schedule: ScheduleDTO): string => {
  const trigger = schedule.trigger;
  if (trigger.trigger_type === 'interval') {
    const seconds = toFiniteNumber(trigger.config.seconds);
    if (!seconds) return '—';
    return formatCompactInterval(seconds);
  }
  if (trigger.trigger_type === 'once') {
    return formatUnixSeconds(toFiniteNumber(trigger.config.run_at));
  }
  if (trigger.trigger_type === 'cron') {
    return formatCronExpression(trigger.config);
  }
  return trigger.trigger_type;
};
```

- [ ] **Step 2: Create `scheduleHelpers.ts`**

`frontend/src/pages/tasks-pages/utils/scheduleHelpers.ts`:

```ts
import type { ScheduleActivityDTO, ScheduleDTO } from '@/api';

export const getSchedulePayloadValue = (schedule: ScheduleDTO, key: string): unknown =>
  schedule.metadata?.[key] ?? schedule.target_payload?.[key];

export const getScheduleStringValue = (schedule: ScheduleDTO, key: string): string => {
  const value = getSchedulePayloadValue(schedule, key);
  return typeof value === 'string' ? value.trim() : '';
};

export const getScheduleTitle = (schedule: ScheduleDTO): string => {
  const displayName = getSchedulePayloadValue(schedule, 'display_name')
    ?? getSchedulePayloadValue(schedule, 'title')
    ?? getSchedulePayloadValue(schedule, 'source_type')
    ?? getSchedulePayloadValue(schedule, 'plugin_id');
  return typeof displayName === 'string' && displayName.trim()
    ? displayName
    : schedule.schedule_id;
};

export const getScheduleTargetKind = (schedule: ScheduleDTO): string => (
  getScheduleStringValue(schedule, 'target_kind')
  || getScheduleStringValue(schedule, 'kind')
  || schedule.target_type
);

export const getScheduleTargetKindLabelKey = (schedule: ScheduleDTO): string => {
  const kind = getScheduleTargetKind(schedule);
  if (schedule.target_type === 'user_agent_task' && kind === 'agent_task') {
    return 'prompt';
  }
  return kind;
};

export const getScheduleTargetKindFallback = (schedule: ScheduleDTO): string => (
  getScheduleTargetKindLabelKey(schedule) === 'prompt'
    ? 'Prompt'
    : getScheduleTargetKind(schedule)
);

export const getSchedulePrompt = (schedule: ScheduleDTO): string => (
  getScheduleStringValue(schedule, 'prompt')
  || getScheduleStringValue(schedule, 'message')
  || getScheduleStringValue(schedule, 'goal')
);

export const isPromptBackedSchedule = (schedule: ScheduleDTO): boolean => (
  schedule.target_type === 'user_agent_task'
  && getScheduleTargetKind(schedule) === 'agent_task'
);

export const getScheduleTargetLabelKey = (schedule: ScheduleDTO): string => (
  isPromptBackedSchedule(schedule)
    ? `tasks.scheduled.targetKinds.${getScheduleTargetKindLabelKey(schedule)}`
    : `tasks.scheduled.targetTypes.${schedule.target_type}`
);

export const getScheduleTargetLabelFallback = (schedule: ScheduleDTO): string => (
  isPromptBackedSchedule(schedule)
    ? getScheduleTargetKindFallback(schedule)
    : schedule.target_type
);

export const getActivityTitle = (
  activity: ScheduleActivityDTO,
  schedulesById: Record<string, ScheduleDTO>,
): string => {
  const fromActivity = activity.title?.trim();
  if (fromActivity) return fromActivity;
  const schedule = schedulesById[activity.schedule_id];
  return schedule ? getScheduleTitle(schedule) : activity.schedule_id;
};

export const getSensorPluginId = (schedule: ScheduleDTO): string => (
  getScheduleStringValue(schedule, 'plugin_id') || schedule.target_key.split(':')[0] || schedule.target_key
);
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/tasks-pages/utils/scheduleHelpers.ts \
        frontend/src/pages/tasks-pages/utils/scheduleFormatters.ts
git commit -m "refactor(tasks): extract schedule helpers and formatters"
```

These modules are not yet used; remaining tasks will import them.

---

### Task 3: Extend `schedulesApi` (create + expanded listActivity)

**Files:**
- Modify: `frontend/src/api/modules/schedules.ts`
- Test: `frontend/src/__tests__/schedulesApi.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/schedulesApi.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('@/api/client', () => ({
  api: {
    get: apiGet,
    post: apiPost,
    patch: vi.fn(),
    delete: vi.fn(),
  },
  unwrapGatewayPayload: <T>(value: T) => value,
}));

import { schedulesApi } from '@/api/modules/schedules';

describe('schedulesApi', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
  });

  it('listActivity passes since/until/limit/targetTypes/statuses query params', async () => {
    apiGet.mockResolvedValue({ activities: [] });
    await schedulesApi.listActivity({
      sinceSeconds: 1000,
      untilSeconds: 2000,
      limit: 50,
      targetTypes: ['user_agent_task', 'memory_l3_summary'],
      statuses: ['succeeded', 'failed'],
    });
    const url = apiGet.mock.calls[0][0] as string;
    expect(url).toContain('since=1000');
    expect(url).toContain('until=2000');
    expect(url).toContain('limit=50');
    expect(url).toContain('target_types=user_agent_task');
    expect(url).toContain('target_types=memory_l3_summary');
    expect(url).toContain('statuses=succeeded');
    expect(url).toContain('statuses=failed');
  });

  it('create posts the correct schedule body', async () => {
    apiPost.mockResolvedValue({ schedule: { schedule_id: 'user-1' } });
    await schedulesApi.create({
      schedule_id: 'user-1',
      display_name: 'Daily summary',
      prompt: 'Summarize my day',
      trigger: { trigger_type: 'interval', config: { seconds: 86400 } },
      enabled: true,
    });
    expect(apiPost).toHaveBeenCalledWith('/schedules', expect.objectContaining({
      schedule_id: 'user-1',
      target_type: 'user_agent_task',
      target_key: 'user-1',
      target_payload: expect.objectContaining({ prompt: 'Summarize my day' }),
      metadata: expect.objectContaining({ display_name: 'Daily summary' }),
      enabled: true,
    }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/__tests__/schedulesApi.test.ts
```

Expected: FAIL — `schedulesApi.create is not a function` and `listActivity` URL missing new params.

- [ ] **Step 3: Implement**

Replace the existing `listActivity`, `ListScheduleActivityResponse`, and `schedulesApi` export in `frontend/src/api/modules/schedules.ts` with the following (keep the rest of the file unchanged):

```ts
export type ScheduleActivityStatus =
  | 'running'
  | 'queued'
  | 'upcoming'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | string;

export interface ScheduleActivityDTO {
  activity_id: string;
  schedule_id: string;
  title?: string | null;
  target_type: ScheduleTargetType;
  target_key: string;
  status: ScheduleActivityStatus;
  planned_at?: number | null;
  started_at?: number | null;
  finished_at?: number | null;
  duration_ms?: number | null;
  cancellable: boolean;
  cancel_kind?: 'sensor_sync_job' | string | null;
  error?: string | null;
  background_task_id?: string | null;
}

export interface ListScheduleActivityResponse {
  activities: ScheduleActivityDTO[];
  total?: number;
}

export interface ListActivityParams {
  sinceSeconds?: number;
  untilSeconds?: number;
  limit?: number;
  targetTypes?: string[];
  statuses?: string[];
}

export interface CreateScheduleRequest {
  schedule_id: string;
  display_name: string;
  prompt: string;
  trigger: ScheduleTriggerDTO;
  enabled: boolean;
}

export interface CreateScheduleResponse {
  schedule: ScheduleDTO;
}
```

Replace the `schedulesApi` object's `listActivity` method and add `create`:

```ts
  async listActivity(params: ListActivityParams = {}): Promise<ListScheduleActivityResponse> {
    const search = new URLSearchParams();
    if (params.sinceSeconds !== undefined) search.set('since', String(params.sinceSeconds));
    if (params.untilSeconds !== undefined) search.set('until', String(params.untilSeconds));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    (params.targetTypes ?? []).forEach((t) => search.append('target_types', t));
    (params.statuses ?? []).forEach((s) => search.append('statuses', s));
    const query = search.toString();
    const response = await api.get<ListScheduleActivityResponse>(
      `/schedules/activity${query ? `?${query}` : ''}`,
    );
    return unwrapGatewayPayload(response);
  },

  async create(body: CreateScheduleRequest): Promise<CreateScheduleResponse> {
    const wireBody = {
      schedule_id: body.schedule_id,
      target_type: 'user_agent_task' as const,
      target_key: body.schedule_id,
      trigger: body.trigger,
      target_payload: { prompt: body.prompt, kind: 'agent_task' },
      metadata: { display_name: body.display_name, target_kind: 'agent_task' },
      enabled: body.enabled,
    };
    const response = await api.post<CreateScheduleResponse>('/schedules', wireBody);
    return unwrapGatewayPayload(response);
  },
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/__tests__/schedulesApi.test.ts
```

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/schedules.ts \
        frontend/src/__tests__/schedulesApi.test.ts
git commit -m "feat(api/schedules): add create() and expanded listActivity() params"
```

---

### Task 4: New `useSchedulesStore` for running count + cache

**Files:**
- Create: `frontend/src/stores/schedules.ts`
- Modify: `frontend/src/stores/index.ts` (barrel export)
- Test: `frontend/src/__tests__/schedulesStore.test.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/schedulesStore.test.ts`:

```ts
import { describe, expect, it, beforeEach } from 'vitest';
import { useSchedulesStore } from '@/stores/schedules';
import type { ScheduleDTO } from '@/api';

const makeSchedule = (id: string, running: boolean, enabled = true): ScheduleDTO => ({
  schedule_id: id,
  target_type: 'user_agent_task',
  target_key: id,
  trigger: { trigger_type: 'interval', config: { seconds: 60 } },
  target_payload: {},
  enabled,
  metadata: {},
  target_state: {
    target_type: 'user_agent_task',
    target_key: id,
    running,
  },
});

describe('useSchedulesStore', () => {
  beforeEach(() => {
    useSchedulesStore.getState().reset();
  });

  it('hydrate stores schedules and computes running count', () => {
    useSchedulesStore.getState().hydrate([
      makeSchedule('a', true),
      makeSchedule('b', false),
      makeSchedule('c', true),
    ]);
    expect(useSchedulesStore.getState().runningCount).toBe(2);
    expect(useSchedulesStore.getState().schedules).toHaveLength(3);
  });

  it('disabled schedules are excluded from runningCount', () => {
    useSchedulesStore.getState().hydrate([
      makeSchedule('a', true, false),
    ]);
    expect(useSchedulesStore.getState().runningCount).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/__tests__/schedulesStore.test.ts
```

Expected: FAIL — `Cannot find module '@/stores/schedules'`.

- [ ] **Step 3: Implement**

`frontend/src/stores/schedules.ts`:

```ts
import { create } from 'zustand';
import type { ScheduleDTO } from '@/api';

interface SchedulesState {
  schedules: ScheduleDTO[];
  runningCount: number;
  hydrate: (schedules: ScheduleDTO[]) => void;
  reset: () => void;
}

const countRunning = (schedules: ScheduleDTO[]): number =>
  schedules.reduce((acc, s) => acc + (s.enabled && s.target_state?.running ? 1 : 0), 0);

export const useSchedulesStore = create<SchedulesState>((set) => ({
  schedules: [],
  runningCount: 0,
  hydrate: (schedules) =>
    set({ schedules, runningCount: countRunning(schedules) }),
  reset: () => set({ schedules: [], runningCount: 0 }),
}));
```

Add to `frontend/src/stores/index.ts` exports (append):

```ts
export { useSchedulesStore } from './schedules';
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/__tests__/schedulesStore.test.ts
```

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/schedules.ts frontend/src/stores/index.ts \
        frontend/src/__tests__/schedulesStore.test.ts
git commit -m "feat(stores): add useSchedulesStore with runningCount"
```

---

## Phase 2 — Backend activity endpoint expansion

This phase enables a real "调度记录" page by reading the `schedule_executions` table and accepting filter params.

### Task 5: Add `list_executions_filtered` repo method

**Files:**
- Modify: `backend/src/magi/scheduler/execution_repository.py`
- Test: `backend/tests/scheduler/test_execution_repository_filtered.py` *(new)*

- [ ] **Step 1: Write the failing test**

`backend/tests/scheduler/test_execution_repository_filtered.py`:

```python
import time
import pytest
from magi.scheduler.execution_repository import ScheduleExecutionRepository


@pytest.mark.asyncio
async def test_list_executions_filtered_by_window(tmp_path):
    db_path = tmp_path / "scheduler.db"
    repo = ScheduleExecutionRepository(db_path)
    await repo.initialize()

    now = time.time()
    eid1 = await repo.create_execution_record(
        schedule_id="s1", target_type="user_agent_task",
        target_key="s1", manual=False, started_at=now - 3600,
        scheduler_job_id=None,
    )
    await repo.complete_execution_success(execution_id=eid1, finished_at=now - 3500, message="ok")

    eid2 = await repo.create_execution_record(
        schedule_id="s2", target_type="memory_l3_summary",
        target_key="s2", manual=False, started_at=now - 10,
        scheduler_job_id=None,
    )
    await repo.complete_execution_failure(execution_id=eid2, finished_at=now - 5, error="boom")

    # Window of 5 minutes should only see eid2
    rows = await repo.list_executions_filtered(
        since=now - 300, until=now + 1, limit=100,
    )
    ids = [row["execution_id"] for row in rows]
    assert ids == [eid2]

    # Filter by target_type
    rows = await repo.list_executions_filtered(
        since=now - 86400, target_types=["user_agent_task"], limit=100,
    )
    assert [row["execution_id"] for row in rows] == [eid1]

    # Filter by status
    rows = await repo.list_executions_filtered(
        since=now - 86400, statuses=["failure"], limit=100,
    )
    assert [row["execution_id"] for row in rows] == [eid2]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/scheduler/test_execution_repository_filtered.py -v
```

Expected: FAIL — `AttributeError: 'ScheduleExecutionRepository' object has no attribute 'list_executions_filtered'`.

- [ ] **Step 3: Implement**

Append to `backend/src/magi/scheduler/execution_repository.py` inside the `ScheduleExecutionRepository` class (right after `list_executions`):

```python
    async def list_executions_filtered(
        self,
        *,
        since: float | None = None,
        until: float | None = None,
        statuses: list[str] | None = None,
        target_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Return executions within a time window, with optional status/type filters."""
        conditions: list[str] = []
        params: list[object] = []
        if since is not None:
            conditions.append("started_at >= ?")
            params.append(since)
        if until is not None:
            conditions.append("started_at <= ?")
            params.append(until)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            conditions.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if target_types:
            placeholders = ",".join("?" for _ in target_types)
            conditions.append(f"target_type IN ({placeholders})")
            params.extend(target_types)

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = (
            "SELECT execution_id, schedule_id, target_type, target_key, manual, "
            "status, started_at, finished_at, duration_ms, result_message, error, "
            "stats_json, next_cursor, watermark_ts, scheduler_job_id, created_at "
            f"FROM schedule_executions{where_clause} "
            "ORDER BY started_at DESC LIMIT ?"
        )
        params.append(limit)
        async with self._connect() as db:
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
        import json
        return [
            {
                "execution_id": str(row[0]),
                "schedule_id": str(row[1]),
                "target_type": str(row[2]),
                "target_key": str(row[3]),
                "manual": bool(row[4]),
                "status": str(row[5]),
                "started_at": float(row[6]) if row[6] is not None else None,
                "finished_at": float(row[7]) if row[7] is not None else None,
                "duration_ms": float(row[8]) if row[8] is not None else None,
                "result_message": str(row[9]) if row[9] is not None else None,
                "error": str(row[10]) if row[10] is not None else None,
                "stats": json.loads(str(row[11]) or "{}"),
                "next_cursor": str(row[12]) if row[12] is not None else None,
                "watermark_ts": float(row[13]) if row[13] is not None else None,
                "scheduler_job_id": str(row[14]) if row[14] is not None else None,
                "created_at": float(row[15]) if row[15] is not None else None,
            }
            for row in rows
        ]
```

(If `import json` already exists at the top of the file, remove the inline import.)

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && pytest tests/scheduler/test_execution_repository_filtered.py -v
```

Expected: PASS, 1 test.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/scheduler/execution_repository.py \
        backend/tests/scheduler/test_execution_repository_filtered.py
git commit -m "feat(scheduler/execution): add list_executions_filtered with window+status+type"
```

---

### Task 6: Extend `GET /schedules/activity` to merge history

**Files:**
- Modify: `backend/src/magi/api/routers/schedules.py:164-237`
- Test: `backend/tests/api/test_schedules_activity_history.py` *(new)*

The endpoint must:
1. Accept `since` / `until` / `limit` / `statuses` / `target_types` query params.
2. Continue to return outstanding sensor sync jobs (queued/running).
3. Continue to return currently-running non-sensor schedules + upcoming next-run snapshots.
4. **New:** Return rows from `schedule_executions` whose `started_at` falls inside the window.
5. Status mapping when surfacing executions: `success → succeeded`, `failure → failed`, others passthrough.

- [ ] **Step 1: Write the failing test**

`backend/tests/api/test_schedules_activity_history.py`:

```python
import time
import pytest
from httpx import ASGITransport, AsyncClient

from magi.api.app import create_app
from magi.scheduler.execution_repository import ScheduleExecutionRepository


@pytest.mark.asyncio
async def test_activity_endpoint_returns_history_in_window(tmp_path, monkeypatch):
    app = create_app()
    # Insert a fake execution before hitting the endpoint
    repo_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("MAGI_SCHEDULER_DB", str(repo_path))

    repo = ScheduleExecutionRepository(repo_path)
    await repo.initialize()
    now = time.time()
    eid = await repo.create_execution_record(
        schedule_id="user-test", target_type="user_agent_task",
        target_key="user-test", manual=False, started_at=now - 60,
        scheduler_job_id=None,
    )
    await repo.complete_execution_success(execution_id=eid, finished_at=now - 30, message="ok")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/schedules/activity",
            params={"since": now - 300, "until": now + 1, "limit": 50},
        )
    assert resp.status_code == 200
    activities = resp.json()["activities"]
    matches = [a for a in activities if a["activity_id"].startswith("execution:")]
    assert matches, "expected execution-row activity"
    assert matches[0]["status"] == "succeeded"
    assert matches[0]["schedule_id"] == "user-test"
```

> Note: the path `MAGI_SCHEDULER_DB` and the way `create_app` resolves the repo may differ in this codebase. If `monkeypatch.setenv` doesn't wire the repo into the app, use whichever fixture or DI hook the existing scheduler tests use — grep `tests/scheduler` for setup patterns and mirror.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/api/test_schedules_activity_history.py -v
```

Expected: FAIL — no `execution:` activity IDs in the response.

- [ ] **Step 3: Implement**

Replace the `list_schedule_activity` handler in `backend/src/magi/api/routers/schedules.py` with this version. Edit signature + body:

```python
@schedules_router.get("/activity")
async def list_schedule_activity(
    limit: int = Query(default=100, ge=1, le=300),
    since: float | None = Query(default=None),
    until: float | None = Query(default=None),
    statuses: list[str] | None = Query(default=None),
    target_types: list[str] | None = Query(default=None),
) -> dict[str, Any]:
    repository = _repository()
    await repository.initialize()
    execution_repo = _execution_repository()  # add helper accessor (see below)
    await execution_repo.initialize()

    schedules = await repository.list_schedules(enabled_only=False)
    schedule_by_id = {schedule.schedule_id: schedule for schedule in schedules}
    activities: list[dict[str, Any]] = []

    # --- 1) outstanding sensor sync jobs (unchanged) ---
    for job in await repository.list_outstanding_sensor_sync_jobs(limit=limit):
        schedule = schedule_by_id.get(str(job["schedule_id"]))
        title = _schedule_title(schedule) if schedule is not None else str(job["source_type"])
        queued = str(job["status"]) == "queued"
        activities.append({
            "activity_id": f"sensor_job:{job['job_id']}",
            "schedule_id": job["schedule_id"],
            "title": title,
            "target_type": job["target_type"],
            "target_key": job["target_key"],
            "status": job["status"],
            "planned_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": None,
            "duration_ms": None,
            "cancellable": queued,
            "cancel_kind": "sensor_sync_job" if queued else None,
            "error": job["error"],
            "background_task_id": None,
        })

    # --- 2) currently running + upcoming (unchanged behavior, finished_at added) ---
    for schedule in schedules:
        state = await repository.get_schedule_runtime_state(schedule)
        if state.running and schedule.target_type is not ScheduledTargetType.SENSOR_SYNC:
            activities.append({
                "activity_id": f"target:{schedule.target_type.value}:{schedule.target_key}",
                "schedule_id": schedule.schedule_id,
                "title": _schedule_title(schedule),
                "target_type": schedule.target_type.value,
                "target_key": schedule.target_key,
                "status": "running",
                "planned_at": None,
                "started_at": state.last_run_at,
                "finished_at": None,
                "duration_ms": (
                    max(0.0, (time.time() - state.last_run_at) * 1000.0)
                    if state.last_run_at else None
                ),
                "cancellable": False,
                "cancel_kind": None,
                "error": state.last_error,
                "background_task_id": None,
            })
        if state.next_run_at is not None and not state.running:
            activities.append({
                "activity_id": f"upcoming:{schedule.schedule_id}",
                "schedule_id": schedule.schedule_id,
                "title": _schedule_title(schedule),
                "target_type": schedule.target_type.value,
                "target_key": schedule.target_key,
                "status": "upcoming",
                "planned_at": state.next_run_at,
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
                "cancellable": False,
                "cancel_kind": None,
                "error": state.last_error,
                "background_task_id": None,
            })

    # --- 3) NEW: historical executions in window ---
    raw_status_map = {"succeeded": "success", "failed": "failure"}
    repo_statuses: list[str] | None = None
    if statuses:
        repo_statuses = [raw_status_map.get(s, s) for s in statuses]

    history = await execution_repo.list_executions_filtered(
        since=since,
        until=until,
        statuses=repo_statuses,
        target_types=target_types,
        limit=limit,
    )
    display_status_map = {"success": "succeeded", "failure": "failed"}
    for row in history:
        sched = schedule_by_id.get(str(row["schedule_id"]))
        title = _schedule_title(sched) if sched is not None else str(row["target_key"])
        activities.append({
            "activity_id": f"execution:{row['execution_id']}",
            "schedule_id": row["schedule_id"],
            "title": title,
            "target_type": row["target_type"],
            "target_key": row["target_key"],
            "status": display_status_map.get(str(row["status"]), str(row["status"])),
            "planned_at": row["started_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": row["duration_ms"],
            "cancellable": False,
            "cancel_kind": None,
            "error": row["error"],
            "background_task_id": None,  # populated when cross-link lands
        })

    # Optional client-side filter for target_types (covers sensor jobs + live rows too)
    if target_types:
        activities = [a for a in activities if a["target_type"] in set(target_types)]
    if statuses:
        s_set = set(statuses)
        activities = [a for a in activities if a["status"] in s_set]

    activities.sort(key=lambda item: (item["status"] != "running", -(item.get("started_at") or 0)))
    return {"activities": activities[:limit]}
```

Also add an `_execution_repository()` accessor near `_repository()` at the top of the file:

```python
from magi.scheduler.execution_repository import ScheduleExecutionRepository

def _execution_repository() -> ScheduleExecutionRepository:
    return ScheduleExecutionRepository(_repository().db_path)
```

If `_repository()` already exposes the same DB path under a different attribute, mirror that. Verify by grepping the file once.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && pytest tests/api/test_schedules_activity_history.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/schedules.py \
        backend/tests/api/test_schedules_activity_history.py
git commit -m "feat(api/schedules): merge execution history into /activity with filters"
```

---

### Task 7: Verify the activity contract integration (smoke)

- [ ] **Step 1: Run the full backend scheduler suite**

```bash
cd backend && pytest tests/scheduler tests/api -k schedule -v
```

Expected: all pre-existing tests pass; the two new tests pass.

- [ ] **Step 2: If anything fails, debug and re-commit before continuing**

If a pre-existing test broke, it almost certainly depends on the old activity contract (no `finished_at` / `background_task_id`). Update those tests to assert the new shape, commit separately:

```bash
git add backend/tests/...
git commit -m "test(scheduler): update existing assertions for new activity contract"
```

---

## Phase 3 — Page split + routing

### Task 8: Create `TasksPageFrame` shell

**Files:**
- Create: `frontend/src/pages/tasks-pages/TasksPageFrame.tsx`
- Create: `frontend/src/pages/tasks-pages/index.ts`

- [ ] **Step 1: Implement frame component**

`frontend/src/pages/tasks-pages/TasksPageFrame.tsx`:

```tsx
import React, { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface TasksPageFrameProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  filters?: ReactNode;
  actions?: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  children: ReactNode;
}

export const TasksPageFrame: React.FC<TasksPageFrameProps> = ({
  title,
  subtitle,
  icon,
  filters,
  actions,
  onRefresh,
  refreshing,
  children,
}) => {
  const { t } = useTranslation('app');
  return (
    <div className="flex h-full flex-col bg-background">
      <header className="flex items-start justify-between gap-4 border-b border-border/60 px-6 py-5">
        <div>
          <div className="flex items-center gap-2">
            {icon}
            <h1 className="text-lg font-semibold text-foreground">{title}</h1>
          </div>
          {subtitle ? (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {onRefresh ? (
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
              <RefreshCw className={cn('mr-2 h-3.5 w-3.5', refreshing && 'animate-spin')} />
              {refreshing ? t('tasks.page.refreshing') : t('tasks.page.refresh')}
            </Button>
          ) : null}
        </div>
      </header>
      {filters ? (
        <div className="border-b border-border/60 px-6 py-3">{filters}</div>
      ) : null}
      <div className="flex-1 overflow-hidden px-6 py-5">{children}</div>
    </div>
  );
};
```

`frontend/src/pages/tasks-pages/index.ts`:

```ts
export { TasksPageFrame } from './TasksPageFrame';
export { BackgroundTasksPage } from './BackgroundTasksPage';
export { ScheduleConfigPage } from './ScheduleConfigPage';
export { ScheduleActivityPage } from './ScheduleActivityPage';
```

Note: BackgroundTasksPage etc. don't exist yet — that's fine; this index file fails at import only when something tries to import them. Tasks 9–11 add them.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/tasks-pages/TasksPageFrame.tsx \
        frontend/src/pages/tasks-pages/index.ts
git commit -m "feat(tasks-pages): add TasksPageFrame shell"
```

---

### Task 9: Extract shared subcomponents

Move the helper components from `Tasks.tsx` into their own files so all three pages can import them.

**Files (each is a small extraction, no behavior change):**

- Create: `frontend/src/pages/tasks-pages/components/IconActionButton.tsx`
- Create: `frontend/src/pages/tasks-pages/components/TasksPaginationBar.tsx`
- Create: `frontend/src/pages/tasks-pages/components/BackgroundTaskRow.tsx`
- Create: `frontend/src/pages/tasks-pages/components/BackgroundTaskDetailDrawer.tsx`
- Create: `frontend/src/pages/tasks-pages/components/ScheduleEditDrawer.tsx`

- [ ] **Step 1: Copy each component verbatim from `Tasks.tsx`**

For each component, copy the corresponding block from the current `Tasks.tsx`, change the imports to use the new helper paths (`./utils/scheduleHelpers`, `./utils/scheduleFormatters`), and export it as a named export. Specifically:

- `IconActionButton` (lines 402–424 of current `Tasks.tsx`) → `components/IconActionButton.tsx`
- `TasksPaginationBar` + `TasksPaginationBarProps` (lines 324–378) → `components/TasksPaginationBar.tsx`
- `TaskRow` + props (lines 279–322) → renamed file `BackgroundTaskRow.tsx`, exported component renamed `BackgroundTaskRow`. Update the import in callers.
- `TaskDetailDrawer` + props (lines 426–721) → `BackgroundTaskDetailDrawer.tsx`, exported as `BackgroundTaskDetailDrawer`.
- `ScheduleEditDrawer` + props (lines 723–962) → `components/ScheduleEditDrawer.tsx`.

Each extracted file's top imports look like (adapt per component):

```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
// ...lucide imports
import { Button } from '@/components/ui/button';
import { /* helpers used by this component */ } from '../utils/scheduleHelpers';
import { /* formatters used */ } from '../utils/scheduleFormatters';
```

- [ ] **Step 2: Sanity-build**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no new type errors. (The original `Tasks.tsx` will still compile because we haven't deleted anything yet.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/tasks-pages/components/
git commit -m "refactor(tasks-pages): extract shared components from Tasks.tsx"
```

---

### Task 10: Build `BackgroundTasksPage`

**Files:**
- Create: `frontend/src/pages/tasks-pages/BackgroundTasksPage.tsx`

- [ ] **Step 1: Implement**

```tsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { ListChecks } from 'lucide-react';

import {
  backgroundTasksApi,
  type BackgroundTaskDTO,
} from '@/api';
import { useBackgroundTaskStore } from '@/stores/background-tasks';
import { DEFAULT_USER_ID } from '@/constants';
import { TasksPageFrame } from './TasksPageFrame';
import { BackgroundTaskRow } from './components/BackgroundTaskRow';
import { BackgroundTaskDetailDrawer } from './components/BackgroundTaskDetailDrawer';
import { TasksPaginationBar } from './components/TasksPaginationBar';

const BACKGROUND_TASK_PAGE_SIZE = 20;

interface TasksSectionProps {
  title: string;
  tasks: BackgroundTaskDTO[];
  onSelect: (taskId: string) => void;
}
const TasksSection: React.FC<TasksSectionProps> = ({ title, tasks, onSelect }) => {
  if (tasks.length === 0) return null;
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {title} · {tasks.length}
      </h2>
      <div className="space-y-2">
        {tasks.map((task) => (
          <BackgroundTaskRow key={task.task_id} task={task} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
};

export const BackgroundTasksPage: React.FC = () => {
  const { t } = useTranslation('app');
  const tasksById = useBackgroundTaskStore((s) => s.tasksById);
  const orderedIds = useBackgroundTaskStore((s) => s.orderedIds);
  const hydrate = useBackgroundTaskStore((s) => s.hydrate);

  const orderedTasks = useMemo(
    () => orderedIds.map((id) => tasksById[id]).filter((t): t is BackgroundTaskDTO => Boolean(t)),
    [orderedIds, tasksById],
  );

  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    const queryTaskId = searchParams.get('taskId');
    if (queryTaskId && queryTaskId !== selectedTaskId) {
      setSelectedTaskId(queryTaskId);
      const next = new URLSearchParams(searchParams);
      next.delete('taskId');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, selectedTaskId, setSearchParams]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await backgroundTasksApi.list({
        userId: DEFAULT_USER_ID,
        limit: BACKGROUND_TASK_PAGE_SIZE,
        offset,
      });
      if (response.total > 0 && offset >= response.total) {
        const fallbackOffset = Math.max(
          0,
          (Math.ceil(response.total / BACKGROUND_TASK_PAGE_SIZE) - 1) * BACKGROUND_TASK_PAGE_SIZE,
        );
        if (fallbackOffset !== offset) {
          setOffset(fallbackOffset);
          return;
        }
      }
      hydrate(response.tasks, response.active_count);
      setTotal(response.total);
    } catch {
      toast.error(t('tasks.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [offset, hydrate, t]);

  useEffect(() => { void refresh(); }, [refresh]);

  const { running, queued, finished } = useMemo(() => {
    const r: BackgroundTaskDTO[] = [];
    const q: BackgroundTaskDTO[] = [];
    const f: BackgroundTaskDTO[] = [];
    for (const task of orderedTasks) {
      if (task.status === 'running' || task.status === 'cancelling') r.push(task);
      else if (task.status === 'pending') q.push(task);
      else f.push(task);
    }
    return { running: r, queued: q, finished: f };
  }, [orderedTasks]);

  const isEmpty = !loading && total === 0;

  return (
    <TasksPageFrame
      title={t('tasks.page.title')}
      subtitle={t('tasks.page.subtitle')}
      icon={<ListChecks className="h-5 w-5 text-muted-foreground" />}
      onRefresh={() => void refresh()}
      refreshing={loading}
    >
      <div className="flex h-full min-h-0 flex-col gap-4">
        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {isEmpty ? (
            <div className="flex h-full min-h-[20rem] flex-col items-center justify-center rounded-lg border border-dashed border-border/60 px-6 py-16 text-center">
              <ListChecks className="mb-3 h-10 w-10 text-muted-foreground/70" />
              <h2 className="text-sm font-medium text-foreground">{t('tasks.empty.title')}</h2>
              <p className="mt-1 text-xs text-muted-foreground">{t('tasks.empty.description')}</p>
            </div>
          ) : (
            <div className="w-full space-y-6 pb-1">
              <TasksSection title={t('tasks.sections.running')} tasks={running} onSelect={setSelectedTaskId} />
              <TasksSection title={t('tasks.sections.queued')} tasks={queued} onSelect={setSelectedTaskId} />
              <TasksSection title={t('tasks.sections.finished')} tasks={finished} onSelect={setSelectedTaskId} />
            </div>
          )}
        </div>
        <div className="shrink-0">
          <TasksPaginationBar
            total={total}
            offset={offset}
            limit={BACKGROUND_TASK_PAGE_SIZE}
            loading={loading}
            onPageChange={setOffset}
          />
        </div>
      </div>
      <BackgroundTaskDetailDrawer
        taskId={selectedTaskId}
        onClose={() => setSelectedTaskId(null)}
        onMutated={refresh}
      />
    </TasksPageFrame>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/tasks-pages/BackgroundTasksPage.tsx
git commit -m "feat(tasks-pages): BackgroundTasksPage"
```

---

### Task 11: Build `ScheduleConfigPage` (minimal scaffold)

This task scaffolds the page with just data load + table — filters & create come in Phase 5. Doing the scaffold first lets us wire routing in Phase 3 without orphan modules.

**Files:**
- Create: `frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx`
- Create: `frontend/src/pages/tasks-pages/components/ScheduleConfigTable.tsx`

- [ ] **Step 1: Implement table** (copy enabled-schedules table from `Tasks.tsx:1085-1229`, change imports to new helpers, accept `schedules`, callbacks, `editingScheduleId`, etc., as props).

`frontend/src/pages/tasks-pages/components/ScheduleConfigTable.tsx`:

```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Play, Power, PowerOff, Settings, Trash2 } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import type { ScheduleDTO } from '@/api';
import {
  getScheduleTargetLabelKey,
  getScheduleTargetLabelFallback,
  getScheduleTitle,
} from '../utils/scheduleHelpers';
import {
  formatScheduleTableTime,
  getScheduleTriggerSummary,
} from '../utils/scheduleFormatters';
import { IconActionButton } from './IconActionButton';

export interface ScheduleConfigTableProps {
  schedules: ScheduleDTO[];
  loading: boolean;
  emptyMessage: string;
  editingScheduleId: string | null;
  runningScheduleId: string | null;
  togglingScheduleId: string | null;
  deletingScheduleId: string | null;
  onSelectSchedule: (s: ScheduleDTO) => void;
  onRunSchedule: (s: ScheduleDTO) => void;
  onToggleSchedule: (s: ScheduleDTO) => void;
  onDeleteSchedule: (s: ScheduleDTO) => void;
  onOpenSettings: (s: ScheduleDTO) => void;
  onOpenInfo: (s: ScheduleDTO) => void;
}

export const ScheduleConfigTable: React.FC<ScheduleConfigTableProps> = (props) => {
  const { t } = useTranslation('app');
  const {
    schedules, loading, emptyMessage,
    editingScheduleId, runningScheduleId, togglingScheduleId, deletingScheduleId,
    onSelectSchedule, onRunSchedule, onToggleSchedule, onDeleteSchedule,
    onOpenSettings, onOpenInfo,
  } = props;

  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="w-[32%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
            <th className="w-[18%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.rule')}</th>
            <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.lastRun')}</th>
            <th className="w-[17%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.nextRun')}</th>
            <th className="w-[16%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {!loading && schedules.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-4 py-8 text-center text-xs text-muted-foreground">
                {emptyMessage}
              </td>
            </tr>
          ) : schedules.map((schedule) => {
            const sensorOwned = schedule.target_type === 'sensor_sync';
            const systemOwned = schedule.editable === false && !sensorOwned;
            const selected = editingScheduleId === schedule.schedule_id;
            const scheduleRunning = Boolean(schedule.target_state?.running);
            const runPending = runningScheduleId === schedule.schedule_id;
            const togglePending = togglingScheduleId === schedule.schedule_id;
            const deletePending = deletingScheduleId === schedule.schedule_id;
            const rowBusy = togglePending || deletePending;
            const runDisabled = scheduleRunning || runningScheduleId !== null || rowBusy;
            const triggerMode = t(`tasks.scheduled.triggerTypes.${schedule.trigger.trigger_type}`, {
              defaultValue: schedule.trigger.trigger_type,
            });
            const triggerText = `${triggerMode} ${getScheduleTriggerSummary(schedule)}`.trim();
            const scheduleTypeLabel = t(getScheduleTargetLabelKey(schedule), {
              defaultValue: getScheduleTargetLabelFallback(schedule),
            });
            const toggleLabel = schedule.enabled
              ? t('tasks.scheduled.actions.disable')
              : t('tasks.scheduled.actions.enable');

            return (
              <tr
                key={schedule.schedule_id}
                className={cn(
                  'bg-background/60 transition-colors',
                  selected && 'bg-primary/5',
                  !selected && 'hover:bg-muted/35',
                  !sensorOwned && !systemOwned && 'cursor-pointer',
                )}
                onClick={() => { if (!sensorOwned && !systemOwned) onSelectSchedule(schedule); }}
              >
                <td className="px-4 py-3 align-middle">
                  <div className="flex items-center gap-2">
                    <div className="truncate font-medium text-foreground" title={getScheduleTitle(schedule)}>
                      {getScheduleTitle(schedule)}
                    </div>
                    {!schedule.enabled ? (
                      <span className="rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-[10px] uppercase tracking-wide">
                        {t('tasks.scheduled.status.disabled')}
                      </span>
                    ) : null}
                    {scheduleRunning ? (
                      <span className="rounded-full bg-emerald-500/15 text-emerald-500 px-2 py-0.5 text-[10px] uppercase tracking-wide">
                        {t('tasks.scheduled.status.running')}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted-foreground" title={scheduleTypeLabel}>
                    {scheduleTypeLabel}
                  </div>
                </td>
                <td className="px-4 py-3 align-middle text-xs text-foreground" title={triggerText}>{triggerText}</td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatScheduleTableTime(schedule.target_state?.last_run_at)}</td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatScheduleTableTime(schedule.target_state?.next_run_at)}</td>
                <td className="px-4 py-3 align-middle">
                  <div className="flex justify-end gap-1">
                    <IconActionButton
                      variant="outline"
                      disabled={runDisabled}
                      label={t('tasks.scheduled.actions.runNow')}
                      icon={runPending ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      onClick={(e) => { e.stopPropagation(); onRunSchedule(schedule); }}
                    />
                    {!sensorOwned && !systemOwned ? (
                      <IconActionButton
                        variant="outline"
                        label={t('tasks.scheduled.actions.edit')}
                        icon={<Pencil className="h-3.5 w-3.5" />}
                        disabled={rowBusy}
                        onClick={(e) => { e.stopPropagation(); onSelectSchedule(schedule); }}
                      />
                    ) : null}
                    {sensorOwned ? (
                      <IconActionButton
                        variant="secondary"
                        label={t('tasks.scheduled.actions.openSettings')}
                        icon={<Settings className="h-3.5 w-3.5" />}
                        disabled={rowBusy}
                        onClick={(e) => { e.stopPropagation(); onOpenSettings(schedule); }}
                      />
                    ) : null}
                    {systemOwned ? (
                      <IconActionButton
                        variant="secondary"
                        label={t('tasks.scheduled.actions.openInfo')}
                        icon={<Settings className="h-3.5 w-3.5" />}
                        disabled={rowBusy}
                        onClick={(e) => { e.stopPropagation(); onOpenInfo(schedule); }}
                      />
                    ) : null}
                    <IconActionButton
                      variant="outline"
                      label={toggleLabel}
                      disabled={rowBusy || scheduleRunning}
                      icon={togglePending ? <LoadingSpinner className="h-3.5 w-3.5" /> : (
                        schedule.enabled ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />
                      )}
                      onClick={(e) => { e.stopPropagation(); onToggleSchedule(schedule); }}
                    />
                    {!sensorOwned && !systemOwned ? (
                      <IconActionButton
                        variant="ghost"
                        label={t('tasks.scheduled.actions.delete')}
                        className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                        disabled={rowBusy || scheduleRunning}
                        icon={deletePending ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Trash2 className="h-3.5 w-3.5" />}
                        onClick={(e) => { e.stopPropagation(); onDeleteSchedule(schedule); }}
                      />
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
```

- [ ] **Step 2: Scaffold `ScheduleConfigPage.tsx`**

For now, minimal: load schedules (enabled-only true), no filters, no create. We'll add those in Phase 5.

```tsx
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { CalendarClock } from 'lucide-react';

import { schedulesApi, type ScheduleDTO } from '@/api';
import { useChatShellStore } from '@/stores';
import { useSchedulesStore } from '@/stores/schedules';
import { TasksPageFrame } from './TasksPageFrame';
import { ScheduleConfigTable } from './components/ScheduleConfigTable';
import { ScheduleEditDrawer } from './components/ScheduleEditDrawer';

export const ScheduleConfigPage: React.FC = () => {
  const { t } = useTranslation('app');
  const setActivePanel = useChatShellStore((s) => s.setActivePanel);
  const setSettingsNavigationIntent = useChatShellStore((s) => s.setSettingsNavigationIntent);

  const hydrate = useSchedulesStore((s) => s.hydrate);
  const schedules = useSchedulesStore((s) => s.schedules);

  const [loading, setLoading] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ScheduleDTO | null>(null);
  const [runningScheduleId, setRunningScheduleId] = useState<string | null>(null);
  const [togglingScheduleId, setTogglingScheduleId] = useState<string | null>(null);
  const [deletingScheduleId, setDeletingScheduleId] = useState<string | null>(null);

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await schedulesApi.list({ enabledOnly: true });
      hydrate(res.schedules);
    } catch {
      toast.error(t('tasks.scheduled.feedback.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [hydrate, t]);

  useEffect(() => { void loadSchedules(); }, [loadSchedules]);

  const handleRun = async (s: ScheduleDTO) => {
    if (s.target_state?.running || runningScheduleId) return;
    setRunningScheduleId(s.schedule_id);
    try {
      await schedulesApi.run(s.schedule_id);
      toast.success(t('tasks.scheduled.feedback.runSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.runFailed'));
    } finally { setRunningScheduleId(null); }
  };
  const handleToggle = async (s: ScheduleDTO) => {
    setTogglingScheduleId(s.schedule_id);
    try {
      await schedulesApi.update(s.schedule_id, { enabled: !s.enabled });
      toast.success(t('tasks.scheduled.feedback.toggleSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.toggleFailed'));
    } finally { setTogglingScheduleId(null); }
  };
  const handleDelete = async (s: ScheduleDTO) => {
    setDeletingScheduleId(s.schedule_id);
    try {
      await schedulesApi.remove(s.schedule_id);
      toast.success(t('tasks.scheduled.feedback.deleteSuccess'));
      await loadSchedules();
    } catch {
      toast.error(t('tasks.scheduled.feedback.deleteFailed'));
    } finally { setDeletingScheduleId(null); }
  };
  const handleOpenSettings = (s: ScheduleDTO) => {
    const sourceName = s.settings_link?.source_name;
    if (s.settings_link?.section === 'timeline' && sourceName) {
      setSettingsNavigationIntent({ section: 'timeline', source: sourceName });
      setActivePanel('settings');
      return;
    }
    setSettingsNavigationIntent(null);
    setActivePanel('settings');
  };
  const handleOpenInfo = (_s: ScheduleDTO) => {
    // wired in Phase 5
  };

  return (
    <TasksPageFrame
      title={t('tasks.scheduled.pageTitle')}
      subtitle={t('tasks.scheduled.pageSubtitle')}
      icon={<CalendarClock className="h-5 w-5 text-muted-foreground" />}
      onRefresh={() => void loadSchedules()}
      refreshing={loading}
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 overflow-y-auto pr-1">
        <ScheduleConfigTable
          schedules={schedules}
          loading={loading}
          emptyMessage={t('tasks.scheduled.empty.enabled')}
          editingScheduleId={editingSchedule?.schedule_id ?? null}
          runningScheduleId={runningScheduleId}
          togglingScheduleId={togglingScheduleId}
          deletingScheduleId={deletingScheduleId}
          onSelectSchedule={setEditingSchedule}
          onRunSchedule={handleRun}
          onToggleSchedule={handleToggle}
          onDeleteSchedule={handleDelete}
          onOpenSettings={handleOpenSettings}
          onOpenInfo={handleOpenInfo}
        />
      </div>
      <ScheduleEditDrawer
        schedule={editingSchedule}
        onClose={() => setEditingSchedule(null)}
        onSaved={() => void loadSchedules()}
      />
    </TasksPageFrame>
  );
};
```

- [ ] **Step 3: Scaffold `ScheduleActivityPage.tsx`** (placeholder; Phase 6 fills it in)

```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
import { History } from 'lucide-react';
import { TasksPageFrame } from './TasksPageFrame';

export const ScheduleActivityPage: React.FC = () => {
  const { t } = useTranslation('app');
  return (
    <TasksPageFrame
      title={t('tasks.activity.pageTitle')}
      subtitle={t('tasks.activity.pageSubtitle')}
      icon={<History className="h-5 w-5 text-muted-foreground" />}
    >
      <div className="text-sm text-muted-foreground">…</div>
    </TasksPageFrame>
  );
};
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/tasks-pages/
git commit -m "feat(tasks-pages): scaffold ScheduleConfigPage and ScheduleActivityPage"
```

---

### Task 12: Routing + legacy redirect

**Files:**
- Modify: `frontend/src/router/index.tsx`

- [ ] **Step 1: Add lazy imports near the existing `TasksPage` import**

Replace the existing `TasksPage` lazy declaration (around line 38–40) with:

```tsx
const BackgroundTasksPage = React.lazy(() =>
  import('../pages/tasks-pages').then((m) => ({ default: m.BackgroundTasksPage }))
);
const ScheduleConfigPage = React.lazy(() =>
  import('../pages/tasks-pages').then((m) => ({ default: m.ScheduleConfigPage }))
);
const ScheduleActivityPage = React.lazy(() =>
  import('../pages/tasks-pages').then((m) => ({ default: m.ScheduleActivityPage }))
);
```

- [ ] **Step 2: Replace the `path: 'tasks'` route block** (lines ~221–227) with:

```tsx
{
  path: 'tasks',
  children: [
    { index: true, element: <Navigate to="/tasks/background" replace /> },
    {
      path: 'background',
      element: (
        <React.Suspense fallback={<LoadingFallback />}>
          <BackgroundTasksPage />
        </React.Suspense>
      ),
    },
    {
      path: 'schedules',
      children: [
        {
          index: true,
          element: (
            <React.Suspense fallback={<LoadingFallback />}>
              <ScheduleConfigPage />
            </React.Suspense>
          ),
        },
        {
          path: 'activity',
          element: (
            <React.Suspense fallback={<LoadingFallback />}>
              <ScheduleActivityPage />
            </React.Suspense>
          ),
        },
      ],
    },
  ],
},
```

- [ ] **Step 3: Legacy `?tab=` redirect** — handled in `BackgroundTasksPage` by interpreting `tab=scheduled` and navigating, or via a tiny `<TasksLegacyRedirect>` component at `/tasks` index. Easier: in `BackgroundTasksPage`, before render, check `searchParams.get('tab')` and `navigate('/tasks/schedules')` once. Add the following at the top of the existing `useEffect` chain in `BackgroundTasksPage`:

```tsx
import { useNavigate } from 'react-router-dom';
// ...
const navigate = useNavigate();
useEffect(() => {
  const legacyTab = searchParams.get('tab');
  if (legacyTab === 'scheduled') {
    navigate('/tasks/schedules', { replace: true });
  }
}, [searchParams, navigate]);
```

- [ ] **Step 4: Delete the old page**

```bash
rm frontend/src/pages/Tasks.tsx
```

- [ ] **Step 5: Sanity-build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm vitest run --reporter=verbose
```

Expected: type-checks pass. The existing `tasksPage.test.tsx` will FAIL — that's expected; Task 25 splits it. Mark this transient failure and continue.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/router/index.tsx
git rm frontend/src/pages/Tasks.tsx
git commit -m "feat(router): split /tasks into /background and /schedules subroutes"
```

---

## Phase 4 — Sidebar Tasks panel

### Task 13: `renderTasksPanel`

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Add imports**

At the top of `Sidebar.tsx`, add (or merge with existing lucide imports):

```tsx
import { CalendarClock, History } from 'lucide-react';
import { useSchedulesStore } from '@/stores/schedules';
```

- [ ] **Step 2: Define destinations** — near `MEMORY_DESTINATIONS` (around line 40), add:

```tsx
const TASKS_DESTINATIONS = [
  { key: 'background', path: '/tasks/background', icon: ListChecks },
  { key: 'schedules', path: '/tasks/schedules', icon: CalendarClock },
  { key: 'activity', path: '/tasks/schedules/activity', icon: History },
] as const;
```

- [ ] **Step 3: Add `renderTasksPanel`** — near `renderMemoryPanel` (around line 476):

```tsx
const renderTasksPanel = () => {
  const tasksBackgroundActive =
    location.pathname === '/tasks/background' || location.pathname === '/tasks';
  const schedulesActive =
    location.pathname === '/tasks/schedules' || location.pathname === '/tasks/schedules/';
  const activityActive = location.pathname === '/tasks/schedules/activity';
  const activeMap: Record<string, boolean> = {
    background: tasksBackgroundActive,
    schedules: schedulesActive,
    activity: activityActive,
  };
  const backgroundBadge = tasksActiveCount;
  const runningSchedules = useSchedulesStore.getState().runningCount;

  return (
    <div className="flex min-h-0 flex-1 flex-col pt-2" data-testid="sidebar-tasks-panel">
      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 py-2.5 pr-3 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
        <div className="space-y-0.5">
          {TASKS_DESTINATIONS.map(({ key, path, icon: Icon }) => {
            const active = activeMap[key];
            const badge =
              key === 'background' ? backgroundBadge :
              key === 'activity' ? runningSchedules : 0;
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setActivePanel('tasks');
                  navigate(path);
                }}
                aria-label={t(`shell.tasks.${key}`)}
                aria-current={active ? 'page' : undefined}
                className={panelNavButtonClass(active)}
              >
                <Icon className="mr-2 h-3.5 w-3.5" />
                <span className="min-w-0 flex-1 truncate font-medium">
                  {t(`shell.tasks.${key}`)}
                </span>
                {badge > 0 ? (
                  <span className="inline-flex min-w-4 items-center justify-center rounded-full bg-[hsl(var(--sidebar-badge))] px-1 text-[9px] font-medium leading-4 text-[hsl(var(--sidebar-badge-foreground))]">
                    {Math.min(badge, 99)}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
```

- [ ] **Step 4: Wire into `renderPanelContent`** (around line 530):

```tsx
const renderPanelContent = () => {
  if (openPanel === 'conversation') return renderConversationPanel();
  if (openPanel === 'memory') return renderMemoryPanel();
  if (openPanel === 'timeline') return renderTimelinePanel();
  if (openPanel === 'tasks') return renderTasksPanel();
  if (!openPanel) return null;
  return (
    <div className="flex min-h-0 flex-1 flex-col pt-2" data-testid={`sidebar-${openPanel}-panel`}>
      <div className="min-h-0 flex-1" />
    </div>
  );
};
```

- [ ] **Step 5: Update activity icon badge to merge counts**

Find where `tasksActiveCount` is passed as `badgeCount` (around line 624):

```tsx
{renderActivityButton(
  'tasks',
  t('shell.tasks.label'),
  <ListChecks className="h-[18px] w-[18px]" />,
  tasksActive,
  tasksActiveCount + useSchedulesStore.getState().runningCount,
)}
```

Note: this static `.getState()` doesn't re-render on store change. Convert to a subscribing read at the top of the component:

```tsx
const runningSchedulesCount = useSchedulesStore((s) => s.runningCount);
```

and pass `tasksActiveCount + runningSchedulesCount`.

- [ ] **Step 6: Add tasks routes to `tasksActive`**

Find `const tasksActive = activePanel === 'tasks' || location.pathname === '/tasks';` (line 305) and replace with:

```tsx
const tasksActive = activePanel === 'tasks' || location.pathname.startsWith('/tasks');
```

- [ ] **Step 7: Sanity-build**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean. Tests still failing pending Task 25 — that's known.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(sidebar): render tasks panel with 3 nav entries + running badge"
```

---

## Phase 5 — Schedule Config page enhancements

### Task 14: Add `CategoryChipBar`

**Files:**
- Create: `frontend/src/pages/tasks-pages/components/CategoryChipBar.tsx`

- [ ] **Step 1: Implement**

```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { SCHEDULE_CATEGORIES, type ScheduleCategory } from '../utils/scheduleCategory';

export type CategoryFilter = 'all' | ScheduleCategory;

export interface CategoryChipBarProps {
  value: CategoryFilter;
  counts: Record<CategoryFilter, number>;
  onChange: (value: CategoryFilter) => void;
}

export const CategoryChipBar: React.FC<CategoryChipBarProps> = ({ value, counts, onChange }) => {
  const { t } = useTranslation('app');
  const items: CategoryFilter[] = ['all', ...SCHEDULE_CATEGORIES];
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {items.map((cat) => {
        const active = value === cat;
        const label = t(`tasks.scheduled.categories.${cat}`);
        return (
          <button
            key={cat}
            type="button"
            onClick={() => onChange(cat)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors',
              active
                ? 'border-primary/50 bg-primary/10 text-foreground'
                : 'border-border/60 bg-background hover:bg-muted/50 text-muted-foreground'
            )}
          >
            <span>{label}</span>
            <span className={cn('inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1 text-[10px]',
              active ? 'bg-primary/20 text-primary' : 'bg-muted text-muted-foreground'
            )}>{counts[cat] ?? 0}</span>
          </button>
        );
      })}
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/tasks-pages/components/CategoryChipBar.tsx
git commit -m "feat(tasks-pages): add CategoryChipBar"
```

---

### Task 15: Wire filters into ScheduleConfigPage

**Files:**
- Modify: `frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx`

- [ ] **Step 1: Track `category` + `showDisabled` state**

```tsx
const [category, setCategory] = useState<CategoryFilter>('all');
const [showDisabled, setShowDisabled] = useState(false);
```

- [ ] **Step 2: Adjust `loadSchedules` to fetch all when needed**

```tsx
const res = await schedulesApi.list({ enabledOnly: !showDisabled });
```

(re-fetch when `showDisabled` changes — include `showDisabled` in the `useCallback` deps).

- [ ] **Step 3: Compute filtered + counts**

```tsx
import { scheduleCategory, SCHEDULE_CATEGORIES } from './utils/scheduleCategory';
import type { CategoryFilter } from './components/CategoryChipBar';

const counts = useMemo<Record<CategoryFilter, number>>(() => {
  const init: Record<CategoryFilter, number> = {
    all: 0, user: 0, sensor: 0, memory: 0, timeline: 0, other: 0,
  };
  for (const s of schedules) {
    const c = scheduleCategory(s.target_type);
    init.all += 1;
    init[c] = (init[c] ?? 0) + 1;
  }
  return init;
}, [schedules]);

const filtered = useMemo(() => {
  if (category === 'all') return schedules;
  return schedules.filter((s) => scheduleCategory(s.target_type) === category);
}, [schedules, category]);
```

- [ ] **Step 4: Pass to frame and table**

```tsx
<TasksPageFrame
  title={...}
  // ...
  filters={
    <div className="flex items-center justify-between gap-3">
      <CategoryChipBar value={category} counts={counts} onChange={setCategory} />
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <input
          type="checkbox"
          className="h-3.5 w-3.5 accent-primary"
          checked={showDisabled}
          onChange={(e) => setShowDisabled(e.target.checked)}
        />
        {t('tasks.scheduled.filters.showDisabled')}
      </label>
    </div>
  }
  actions={
    <Button size="sm" onClick={() => setCreating(true)}>
      <Plus className="mr-1.5 h-3.5 w-3.5" />
      {t('tasks.scheduled.actions.create')}
    </Button>
  }
>
  <ScheduleConfigTable
    schedules={filtered}
    // ...other props
  />
</TasksPageFrame>
```

Add the missing imports: `Plus` from lucide, `Button` from ui, plus `CategoryChipBar`. State for create drawer: `const [creating, setCreating] = useState(false);` — Task 17 implements the drawer.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx
git commit -m "feat(tasks-pages): wire CategoryChipBar + showDisabled filter into ScheduleConfigPage"
```

---

### Task 16: Sensor grouping by plugin

**Files:**
- Modify: `frontend/src/pages/tasks-pages/components/ScheduleConfigTable.tsx`
- Modify: `frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx`

The simplest implementation: when the active filter is `sensor`, the page passes the schedules pre-grouped to the table. Otherwise it passes them flat. The table accepts an optional `groups` prop that lists `[{ pluginId, label, rows }]` and renders a group header row between groups.

- [ ] **Step 1: Add `groups` prop + render path to `ScheduleConfigTable.tsx`**

Extend the props:

```ts
export interface ScheduleGroup {
  pluginId: string;
  label: string;
  rows: ScheduleDTO[];
}
export interface ScheduleConfigTableProps {
  // ...existing
  groups?: ScheduleGroup[];
}
```

In the component body, if `groups` provided, iterate `groups` and emit a group header `<tr>` followed by the rows:

```tsx
if (groups) {
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full table-fixed text-left text-sm">
        {/* same thead */}
        <tbody className="divide-y divide-border/60">
          {groups.map((group) => (
            <React.Fragment key={group.pluginId}>
              <tr className="bg-muted/30">
                <td colSpan={5} className="px-4 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {group.label}
                </td>
              </tr>
              {group.rows.map((schedule) => renderRow(schedule)) /* extract the row JSX into a function */}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

(Refactor the current per-row `.map((schedule) => { … })` body into a `const renderRow = (schedule: ScheduleDTO) => (…)` so it can be reused.)

- [ ] **Step 2: Build `groups` in `ScheduleConfigPage.tsx` when `category === 'sensor'`**

```tsx
import { getSensorPluginId } from './utils/scheduleHelpers';

const sensorGroups = useMemo(() => {
  if (category !== 'sensor') return undefined;
  const byPlugin = new Map<string, ScheduleDTO[]>();
  for (const s of filtered) {
    const pid = getSensorPluginId(s);
    const list = byPlugin.get(pid) ?? [];
    list.push(s);
    byPlugin.set(pid, list);
  }
  return Array.from(byPlugin.entries()).map(([pluginId, rows]) => ({
    pluginId,
    label: pluginId,
    rows,
  }));
}, [filtered, category]);

// pass groups={sensorGroups} to ScheduleConfigTable
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/tasks-pages/components/ScheduleConfigTable.tsx \
        frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx
git commit -m "feat(tasks-pages): group sensor schedules by plugin when sensor filter active"
```

---

### Task 17: Create-mode for ScheduleEditDrawer

**Files:**
- Modify: `frontend/src/pages/tasks-pages/components/ScheduleEditDrawer.tsx`
- Modify: `frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx`
- Test: `frontend/src/__tests__/scheduleCreate.test.tsx` *(new)*

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const createMock = vi.fn().mockResolvedValue({ schedule: {} });
vi.mock('@/api', async () => {
  const actual = await vi.importActual<typeof import('@/api')>('@/api');
  return {
    ...actual,
    schedulesApi: { ...actual.schedulesApi, create: createMock },
  };
});
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import { ScheduleEditDrawer } from '@/pages/tasks-pages/components/ScheduleEditDrawer';

describe('ScheduleEditDrawer create mode', () => {
  it('submits a new schedule via schedulesApi.create', async () => {
    const onClose = vi.fn();
    const onSaved = vi.fn();
    render(
      <ScheduleEditDrawer
        mode="create"
        schedule={null}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
    await userEvent.type(screen.getByLabelText('tasks.scheduled.fields.displayName'), 'Daily Summary');
    await userEvent.type(screen.getByLabelText('tasks.scheduled.fields.promptText'), 'Summarize today');
    await userEvent.click(screen.getByRole('button', { name: 'tasks.scheduled.actions.save' }));
    expect(createMock).toHaveBeenCalled();
    const body = createMock.mock.calls[0][0];
    expect(body).toMatchObject({
      display_name: 'Daily Summary',
      prompt: 'Summarize today',
      trigger: expect.objectContaining({ trigger_type: 'interval' }),
      enabled: true,
    });
    expect(onSaved).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test (fails because component lacks mode prop)**

```bash
cd frontend && pnpm vitest run src/__tests__/scheduleCreate.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Edit `ScheduleEditDrawer.tsx`**

Add `mode` prop and adapt: when `mode === 'create'`, default fields to empty/sensible defaults; render an extra `display_name` text input; on save call `schedulesApi.create` and generate `schedule_id`.

Sketch of the additions (full edit; merge with existing drawer JSX):

```tsx
import { nanoid } from 'nanoid';  // add nanoid dep if not present, or use Date.now() based id

export interface ScheduleEditDrawerProps {
  mode?: 'edit' | 'create';
  schedule: ScheduleDTO | null;
  onClose: () => void;
  onSaved: () => void;
}

// inside component:
const isCreate = props.mode === 'create';

// new state for create
const [displayName, setDisplayName] = useState('');

// defaults when create
useEffect(() => {
  if (!isCreate) return;
  setEnabled(true);
  setTriggerType('interval');
  setIntervalSeconds('3600');
  setOnceRunAt('');
  setCronConfig(JSON.stringify({ second: '0', minute: '0', hour: '*', day: '*', month: '*', day_of_week: '*' }, null, 2));
  setTargetPrompt('');
  setDisplayName('');
}, [isCreate]);

// in save:
if (isCreate) {
  const id = `user-${(Date.now()).toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  await schedulesApi.create({
    schedule_id: id,
    display_name: displayName.trim() || 'New schedule',
    prompt: targetPrompt.trim(),
    trigger: { trigger_type: triggerType, config },
    enabled,
  });
  toast.success(t('tasks.scheduled.feedback.createSuccess'));
  onSaved();
  onClose();
  return;
}
// ...existing update path
```

Render the `display_name` input in create mode, above the prompt:

```tsx
{isCreate ? (
  <label className="block space-y-2">
    <span className={drawerFieldLabelClass}>{t('tasks.scheduled.fields.displayName')}</span>
    <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
  </label>
) : null}
```

Also flip the open condition from `Boolean(schedule)` to `isCreate || Boolean(schedule)`.

- [ ] **Step 4: Wire into `ScheduleConfigPage.tsx`**

Add a second drawer instance for create mode:

```tsx
<ScheduleEditDrawer
  mode={creating ? 'create' : 'edit'}
  schedule={creating ? null : editingSchedule}
  onClose={() => { setCreating(false); setEditingSchedule(null); }}
  onSaved={() => void loadSchedules()}
/>
```

(Adjust: a single drawer suffices because `mode` derives from state. When `creating` is true, render in create mode; otherwise edit mode with `editingSchedule`.)

- [ ] **Step 5: Run test**

```bash
cd frontend && pnpm vitest run src/__tests__/scheduleCreate.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/tasks-pages/components/ScheduleEditDrawer.tsx \
        frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx \
        frontend/src/__tests__/scheduleCreate.test.tsx
git commit -m "feat(tasks-pages): support create mode on ScheduleEditDrawer"
```

---

### Task 18: ScheduleInfoDrawer for system jobs

**Files:**
- Create: `frontend/src/pages/tasks-pages/components/ScheduleInfoDrawer.tsx`
- Modify: `frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx`

- [ ] **Step 1: Implement**

```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import type { ScheduleDTO } from '@/api';
import { getScheduleTitle } from '../utils/scheduleHelpers';
import { formatUnixSeconds, getScheduleTriggerSummary } from '../utils/scheduleFormatters';

export interface ScheduleInfoDrawerProps {
  schedule: ScheduleDTO | null;
  onClose: () => void;
  onRun: (s: ScheduleDTO) => void;
  onToggle: (s: ScheduleDTO) => void;
}

export const ScheduleInfoDrawer: React.FC<ScheduleInfoDrawerProps> = ({ schedule, onClose, onRun, onToggle }) => {
  const { t } = useTranslation('app');
  const open = Boolean(schedule);
  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent className="flex w-full max-w-none flex-col overflow-hidden sm:max-w-xl">
        {schedule ? (
          <>
            <SheetHeader className="shrink-0 border-b border-border/60 px-8 pb-5 pt-6">
              <SheetTitle>
                {t(`tasks.scheduled.systemJobs.${schedule.target_type}.title`, {
                  defaultValue: getScheduleTitle(schedule),
                })}
              </SheetTitle>
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6 text-sm">
              <p className="leading-6 text-muted-foreground">
                {t(`tasks.scheduled.systemJobs.${schedule.target_type}.description`, {
                  defaultValue: t('tasks.scheduled.systemJobs.fallbackDescription'),
                })}
              </p>
              <dl className="mt-5 grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.fields.triggerType')}</dt>
                  <dd className="mt-1">{getScheduleTriggerSummary(schedule)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.columns.lastRun')}</dt>
                  <dd className="mt-1">{formatUnixSeconds(schedule.target_state?.last_run_at)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('tasks.scheduled.columns.nextRun')}</dt>
                  <dd className="mt-1">{formatUnixSeconds(schedule.target_state?.next_run_at)}</dd>
                </div>
                {schedule.target_state?.last_error ? (
                  <div className="sm:col-span-2">
                    <dt className="text-[11px] font-semibold uppercase tracking-wide text-red-500">{t('tasks.scheduled.fields.lastError')}</dt>
                    <dd className="mt-1 text-red-500">{schedule.target_state.last_error}</dd>
                  </div>
                ) : null}
              </dl>
            </div>
            <div className="shrink-0 px-8 pb-6 pt-3">
              <div className="flex justify-end gap-2">
                <Button variant="outline" size="sm" onClick={() => onRun(schedule)}>{t('tasks.scheduled.actions.runNow')}</Button>
                <Button variant="outline" size="sm" onClick={() => onToggle(schedule)}>
                  {schedule.enabled ? t('tasks.scheduled.actions.disable') : t('tasks.scheduled.actions.enable')}
                </Button>
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
};
```

- [ ] **Step 2: Wire into `ScheduleConfigPage.tsx`**

```tsx
const [infoSchedule, setInfoSchedule] = useState<ScheduleDTO | null>(null);
// pass onOpenInfo={setInfoSchedule} to ScheduleConfigTable

<ScheduleInfoDrawer
  schedule={infoSchedule}
  onClose={() => setInfoSchedule(null)}
  onRun={handleRun}
  onToggle={handleToggle}
/>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/tasks-pages/components/ScheduleInfoDrawer.tsx \
        frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx
git commit -m "feat(tasks-pages): add ScheduleInfoDrawer for system schedules"
```

---

### Task 19: Empty state with user CTA

**Files:**
- Modify: `frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx`

- [ ] **Step 1: Add CTA when `category === 'user'` && filtered length === 0**

In the page's content area, before `<ScheduleConfigTable />`:

```tsx
const showUserCta = category === 'user' && !loading && filtered.length === 0;

{showUserCta ? (
  <div className="flex min-h-[20rem] flex-col items-center justify-center rounded-lg border border-dashed border-border/60 px-6 py-16 text-center">
    <CalendarClock className="mb-3 h-10 w-10 text-muted-foreground/70" />
    <h2 className="text-sm font-medium text-foreground">{t('tasks.scheduled.empty.userCtaTitle')}</h2>
    <p className="mt-1 text-xs text-muted-foreground">{t('tasks.scheduled.empty.userCtaDescription')}</p>
    <Button size="sm" className="mt-4" onClick={() => setCreating(true)}>
      <Plus className="mr-1.5 h-3.5 w-3.5" />
      {t('tasks.scheduled.actions.create')}
    </Button>
  </div>
) : (
  <ScheduleConfigTable ... />
)}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/tasks-pages/ScheduleConfigPage.tsx
git commit -m "feat(tasks-pages): add user-category empty CTA on ScheduleConfigPage"
```

---

## Phase 6 — Schedule Activity page

### Task 20: Build `ScheduleActivityTable`

**Files:**
- Create: `frontend/src/pages/tasks-pages/components/ScheduleActivityTable.tsx`

- [ ] **Step 1: Implement**

```tsx
import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Square } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import type { ScheduleActivityDTO, ScheduleDTO } from '@/api';
import { getActivityTitle, getScheduleTargetLabelKey, getScheduleTargetLabelFallback } from '../utils/scheduleHelpers';
import { formatDuration, formatUnixSeconds } from '../utils/scheduleFormatters';
import { IconActionButton } from './IconActionButton';

export interface ScheduleActivityTableProps {
  activities: ScheduleActivityDTO[];
  schedulesById: Record<string, ScheduleDTO>;
  emptyMessage: string;
  stoppingActivityId: string | null;
  onStop: (a: ScheduleActivityDTO) => void;
  onOpenBackgroundTask: (taskId: string) => void;
}

export const ScheduleActivityTable: React.FC<ScheduleActivityTableProps> = ({
  activities, schedulesById, emptyMessage, stoppingActivityId, onStop, onOpenBackgroundTask,
}) => {
  const { t } = useTranslation('app');
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full table-fixed text-left text-sm">
        <thead className="border-b border-border/60 bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="w-[30%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.name')}</th>
            <th className="w-[12%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.status')}</th>
            <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.plannedAt')}</th>
            <th className="w-[16%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.startedAt')}</th>
            <th className="w-[10%] px-4 py-3 font-medium">{t('tasks.scheduled.columns.duration')}</th>
            <th className="w-[16%] px-4 py-3 text-right font-medium">{t('tasks.scheduled.columns.actions')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {activities.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-4 py-8 text-center text-xs text-muted-foreground">{emptyMessage}</td>
            </tr>
          ) : activities.map((activity) => {
            const linked = schedulesById[activity.schedule_id];
            const typeLabel = linked
              ? t(getScheduleTargetLabelKey(linked), { defaultValue: getScheduleTargetLabelFallback(linked) })
              : t(`tasks.scheduled.targetTypes.${activity.target_type}`, { defaultValue: activity.target_type });
            return (
              <tr key={activity.activity_id} className="bg-background/60">
                <td className="px-4 py-3 align-middle">
                  <div className="truncate font-medium text-foreground" title={getActivityTitle(activity, schedulesById)}>
                    {getActivityTitle(activity, schedulesById)}
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted-foreground">{typeLabel}</div>
                </td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground">
                  {t(`tasks.scheduled.activityStatus.${activity.status}`, { defaultValue: activity.status })}
                </td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatUnixSeconds(activity.planned_at)}</td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatUnixSeconds(activity.started_at)}</td>
                <td className="px-4 py-3 align-middle text-xs text-muted-foreground whitespace-nowrap">{formatDuration(activity.duration_ms)}</td>
                <td className="px-4 py-3 align-middle">
                  <div className="flex justify-end gap-1">
                    {activity.background_task_id ? (
                      <IconActionButton
                        variant="outline"
                        label={t('tasks.scheduled.actions.viewBackgroundTask')}
                        icon={<ChevronRight className="h-3.5 w-3.5" />}
                        onClick={() => onOpenBackgroundTask(activity.background_task_id!)}
                      />
                    ) : null}
                    {activity.cancellable ? (
                      <IconActionButton
                        variant="outline"
                        label={t('tasks.scheduled.actions.stop')}
                        disabled={stoppingActivityId === activity.activity_id}
                        icon={stoppingActivityId === activity.activity_id ? <LoadingSpinner className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                        onClick={() => onStop(activity)}
                      />
                    ) : null}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/tasks-pages/components/ScheduleActivityTable.tsx
git commit -m "feat(tasks-pages): add ScheduleActivityTable"
```

---

### Task 21: Flesh out `ScheduleActivityPage`

**Files:**
- Modify: `frontend/src/pages/tasks-pages/ScheduleActivityPage.tsx`

- [ ] **Step 1: Implement**

```tsx
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { History } from 'lucide-react';

import { schedulesApi, type ScheduleActivityDTO, type ScheduleDTO } from '@/api';
import { TasksPageFrame } from './TasksPageFrame';
import { ScheduleActivityTable } from './components/ScheduleActivityTable';
import { CategoryChipBar, type CategoryFilter } from './components/CategoryChipBar';
import { SCHEDULE_CATEGORIES, scheduleCategory } from './utils/scheduleCategory';

type WindowKey = 'today' | 'last24h' | 'last7d';
const windowToSinceSeconds = (key: WindowKey): number => {
  const now = Date.now() / 1000;
  if (key === 'today') {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.getTime() / 1000;
  }
  if (key === 'last24h') return now - 24 * 3600;
  return now - 7 * 24 * 3600;
};

const STATUS_OPTIONS = ['running', 'queued', 'succeeded', 'failed', 'cancelled'] as const;

export const ScheduleActivityPage: React.FC = () => {
  const { t } = useTranslation('app');
  const navigate = useNavigate();
  const [windowKey, setWindowKey] = useState<WindowKey>('today');
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [statusFilter, setStatusFilter] = useState<string | 'all'>('all');
  const [activities, setActivities] = useState<ScheduleActivityDTO[]>([]);
  const [schedulesById, setSchedulesById] = useState<Record<string, ScheduleDTO>>({});
  const [loading, setLoading] = useState(false);
  const [stoppingActivityId, setStoppingActivityId] = useState<string | null>(null);

  const targetTypes = useMemo(() => {
    if (category === 'all') return undefined;
    return getTargetTypesForCategory(category);
  }, [category]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [act, sched] = await Promise.all([
        schedulesApi.listActivity({
          sinceSeconds: windowToSinceSeconds(windowKey),
          limit: 100,
          targetTypes,
          statuses: statusFilter === 'all' ? undefined : [statusFilter],
        }),
        schedulesApi.list({ enabledOnly: false }),
      ]);
      setActivities(act.activities);
      setSchedulesById(Object.fromEntries(sched.schedules.map((s) => [s.schedule_id, s])));
    } catch {
      toast.error(t('tasks.scheduled.feedback.loadFailed'));
    } finally { setLoading(false); }
  }, [windowKey, targetTypes, statusFilter, t]);

  useEffect(() => { void reload(); }, [reload]);

  const counts = useMemo<Record<CategoryFilter, number>>(() => {
    const init: Record<CategoryFilter, number> = { all: 0, user: 0, sensor: 0, memory: 0, timeline: 0, other: 0 };
    for (const a of activities) {
      init.all += 1;
      init[scheduleCategory(a.target_type)] = (init[scheduleCategory(a.target_type)] ?? 0) + 1;
    }
    return init;
  }, [activities]);

  const handleStop = async (activity: ScheduleActivityDTO) => {
    if (!activity.cancellable) return;
    setStoppingActivityId(activity.activity_id);
    try {
      await schedulesApi.cancelActivity(activity.activity_id);
      toast.success(t('tasks.scheduled.feedback.stopSuccess'));
      await reload();
    } catch {
      toast.error(t('tasks.scheduled.feedback.stopFailed'));
    } finally { setStoppingActivityId(null); }
  };

  return (
    <TasksPageFrame
      title={t('tasks.activity.pageTitle')}
      subtitle={t('tasks.activity.pageSubtitle')}
      icon={<History className="h-5 w-5 text-muted-foreground" />}
      onRefresh={() => void reload()}
      refreshing={loading}
      filters={
        <div className="flex flex-wrap items-center gap-3">
          <WindowSegmented value={windowKey} onChange={setWindowKey} />
          <CategoryChipBar value={category} counts={counts} onChange={setCategory} />
          <StatusSelect value={statusFilter} onChange={setStatusFilter} />
        </div>
      }
    >
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 overflow-y-auto pr-1">
        <ScheduleActivityTable
          activities={activities}
          schedulesById={schedulesById}
          emptyMessage={t('tasks.scheduled.empty.activity')}
          stoppingActivityId={stoppingActivityId}
          onStop={handleStop}
          onOpenBackgroundTask={(taskId) => navigate(`/tasks/background?taskId=${encodeURIComponent(taskId)}`)}
        />
      </div>
    </TasksPageFrame>
  );
};

function getTargetTypesForCategory(category: Exclude<CategoryFilter, 'all'>): string[] {
  switch (category) {
    case 'user': return ['user_agent_task'];
    case 'sensor': return ['sensor_sync'];
    case 'memory': return ['memory_l2_maintenance', 'memory_l3_summary', 'memory_l4_maintenance'];
    case 'timeline': return ['timeline_diary_narrative', 'timeline_standout_rescore', 'timeline_mood_aggregate', 'timeline_representative_asset'];
    default: return [];
  }
}

const WindowSegmented: React.FC<{ value: WindowKey; onChange: (v: WindowKey) => void }> = ({ value, onChange }) => {
  const { t } = useTranslation('app');
  const options: WindowKey[] = ['today', 'last24h', 'last7d'];
  return (
    <div className="inline-flex rounded-md border border-border/60 p-0.5">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          className={`px-2.5 py-1 text-xs font-medium rounded ${value === opt ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted/40'}`}
          onClick={() => onChange(opt)}
        >{t(`tasks.scheduled.filters.window.${opt}`)}</button>
      ))}
    </div>
  );
};

const StatusSelect: React.FC<{ value: string | 'all'; onChange: (v: string | 'all') => void }> = ({ value, onChange }) => {
  const { t } = useTranslation('app');
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as string | 'all')}
      className="h-8 rounded-md border border-input bg-background px-2 text-xs"
    >
      <option value="all">{t('tasks.scheduled.activityStatus.all', { defaultValue: 'All' })}</option>
      {STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>{t(`tasks.scheduled.activityStatus.${s}`)}</option>
      ))}
    </select>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/tasks-pages/ScheduleActivityPage.tsx
git commit -m "feat(tasks-pages): ScheduleActivityPage with window/category/status filters"
```

---

### Task 22: Background task cross-link UI (conditional)

The `background_task_id` field is optional. The activity table already renders the link only when present (Task 20). When backend cross-link lands, no UI change is needed. **No action required this iteration**, but verify by inspection: the UI must not crash with `background_task_id: null`.

- [ ] **Step 1: Smoke verify**

```bash
cd frontend && pnpm vitest run src/__tests__/scheduleActivityPage.test.tsx
```

(test added in Task 25.) Expected: PASS.

---

## Phase 7 — i18n keys

### Task 23: Add new translation keys

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`

- [ ] **Step 1: Append to `zh-CN/app.json`** under `tasks` and `shell`:

```json
{
  "shell": {
    "tasks": {
      "label": "任务",
      "background": "后台任务",
      "schedules": "调度配置",
      "activity": "调度记录"
    }
  },
  "tasks": {
    "scheduled": {
      "pageTitle": "调度配置",
      "pageSubtitle": "管理周期性运行的任务、传感器同步与系统作业。",
      "categories": {
        "all": "全部",
        "user": "用户自定义",
        "sensor": "传感器同步",
        "memory": "记忆维护",
        "timeline": "时间线维护",
        "other": "其他"
      },
      "filters": {
        "showDisabled": "显示已禁用",
        "window": { "today": "今天", "last24h": "近 24 小时", "last7d": "近 7 天" }
      },
      "actions": {
        "create": "新建调度任务",
        "openInfo": "查看说明",
        "viewBackgroundTask": "查看后台任务"
      },
      "status": { "running": "运行中", "disabled": "已禁用" },
      "empty": {
        "userCtaTitle": "还没有调度任务",
        "userCtaDescription": "创建一个 Prompt 调度任务，让它定时帮你运行。",
        "activity": "暂无运行记录"
      },
      "fields": { "displayName": "名称", "lastError": "上次错误" },
      "feedback": { "createSuccess": "已创建", "createFailed": "创建失败" },
      "systemJobs": {
        "fallbackDescription": "由系统自动调度的内部维护作业。",
        "memory_l2_maintenance": { "title": "L2 记忆维护", "description": "整理短期记忆向量索引。" },
        "memory_l3_summary": { "title": "L3 记忆摘要", "description": "周期性地把短期记忆汇总成中期叙事。" },
        "memory_l4_maintenance": { "title": "L4 记忆维护", "description": "维护长期事实图谱。" },
        "timeline_diary_narrative": { "title": "时间线日记", "description": "把当天的事件生成成日记式叙事。" },
        "timeline_standout_rescore": { "title": "时间线亮点重排", "description": "重新计算事件的重要性评分。" },
        "timeline_mood_aggregate": { "title": "情绪聚合", "description": "把情绪记录聚合成日/周视图。" },
        "timeline_representative_asset": { "title": "代表性素材选择", "description": "为时间线事件挑选代表图。" }
      },
      "activityStatus": {
        "all": "全部",
        "running": "运行中",
        "queued": "队列中",
        "upcoming": "即将运行",
        "succeeded": "成功",
        "failed": "失败",
        "cancelled": "已取消"
      }
    },
    "activity": {
      "pageTitle": "调度记录",
      "pageSubtitle": "查看历史执行、当前运行与即将运行的调度。"
    }
  }
}
```

- [ ] **Step 2: Mirror to `en/app.json`** with English wording.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json
git commit -m "i18n(tasks): add keys for redesigned tasks pages"
```

---

## Phase 8 — Test split + final verification

### Task 24: Split `tasksPage.test.tsx` into three spec files

**Files:**
- Delete: `frontend/src/__tests__/tasksPage.test.tsx`
- Create: `frontend/src/__tests__/backgroundTasksPage.test.tsx`
- Create: `frontend/src/__tests__/scheduleConfigPage.test.tsx`
- Create: `frontend/src/__tests__/scheduleActivityPage.test.tsx`

- [ ] **Step 1: Read the existing `tasksPage.test.tsx`** to identify which assertions belong to background tab vs scheduled tab.

- [ ] **Step 2: Create three new spec files**, copying mocks and test cases by responsibility. Each file imports its respective page:

  - `backgroundTasksPage.test.tsx` → imports `BackgroundTasksPage` from `@/pages/tasks-pages`. Asserts list rendering, status grouping, refresh, drawer open by `?taskId=`.
  - `scheduleConfigPage.test.tsx` → imports `ScheduleConfigPage`. Asserts:
    - Category chips switch + counts.
    - `showDisabled` toggle re-fetches with `enabledOnly:false`.
    - Sensor chip groups rows by plugin (assert presence of group-header td).
    - Create button opens drawer; submit calls `schedulesApi.create`.
    - User empty CTA renders when user filter chosen and no rows.
    - Info drawer renders for memory/timeline rows.
  - `scheduleActivityPage.test.tsx` → imports `ScheduleActivityPage`. Asserts:
    - Time window switch re-fetches with new `sinceSeconds`.
    - Status filter passes to API.
    - Background-task link visible only when `background_task_id` set.

Each new file follows the existing mock-pattern from `tasksPage.test.tsx`.

- [ ] **Step 3: Delete old test file + run**

```bash
git rm frontend/src/__tests__/tasksPage.test.tsx
cd frontend && pnpm vitest run src/__tests__/
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/__tests__/backgroundTasksPage.test.tsx \
        frontend/src/__tests__/scheduleConfigPage.test.tsx \
        frontend/src/__tests__/scheduleActivityPage.test.tsx
git rm frontend/src/__tests__/tasksPage.test.tsx 2>/dev/null || true
git commit -m "test(tasks-pages): split tasksPage tests by sub-page"
```

---

### Task 25: End-to-end verification

- [ ] **Step 1: Type-check + lint + tests**

```bash
cd frontend && pnpm tsc --noEmit && pnpm vitest run && pnpm lint
```

Expected: clean.

```bash
cd backend && pytest tests/scheduler tests/api -k schedule -v
```

Expected: clean.

- [ ] **Step 2: Manual verification via preview**

Start the dev server, navigate to:
1. `/tasks/background` — verify list, drawer, pagination work.
2. `/tasks/schedules` — verify category chips, show-disabled toggle, create flow, info drawer.
3. `/tasks/schedules/activity` — verify window switching, status filter, table.
4. Sidebar — open Tasks panel, click each entry; confirm activity-icon badge merges background + running counts.
5. Legacy `/tasks?tab=scheduled` link redirects to `/tasks/schedules`.

Use preview_screenshot to capture each page state for the PR.

- [ ] **Step 3: Final commit (if any fixes)** with a clear message; if no fixes, skip.

---

## Self-Review Notes

**Spec coverage check:**

- IA / routing → Tasks 8, 12. ✓
- Sidebar panel → Task 13. ✓
- Background page extraction → Tasks 9–10. ✓
- Schedule config (filters, sensor grouping, create, info drawer, CTA) → Tasks 14, 15, 16, 17, 18, 19. ✓
- Schedule activity (window, filters, cross-link) → Tasks 20, 21, 22. ✓
- Backend activity history merge → Tasks 5, 6, 7. ✓
- API client `create` + extended `listActivity` → Task 3. ✓
- Store / running count → Tasks 4, 13. ✓
- i18n → Task 23. ✓
- Tests split → Task 24. ✓
- Final verify → Task 25. ✓

**Open items handled:**

- `background_task_id` / `source_schedule_id` cross-link fields: spec marks them optional; Task 22 has the UI render path tolerant of missing values. No new task needed.
- Sensor plugin display name / icon: simplified to using `plugin_id` text in Task 16. If the plugin manifest holds a friendlier name, follow-up.

**Risks:**

- The backend `_execution_repository` accessor (Task 6) needs to share the same DB path as `_repository`. Confirm the existing pattern; the snippet above uses `_repository().db_path` which may not be the actual attribute name. The first run of Task 7's smoke test will surface this.
- `nanoid` is not assumed to be present; Task 17 falls back to a `Date.now()`-based id and that is fine.
