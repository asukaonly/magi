import { beforeEach, describe, expect, it } from 'vitest';

import {
  selectOrderedBackgroundTasks,
  useBackgroundTaskStore,
} from '@/stores/background-tasks';
import type { BackgroundTaskDTO, BackgroundTaskSpecDTO } from '@/api';

const DEFAULT_SPEC: BackgroundTaskSpecDTO = {
  user_id: 'local_user',
  session_id: 'session-1',
  origin_turn_id: 'turn-1',
  title: 'Task',
  goal: 'Goal',
  selected_tools: [],
  workspace_path: null,
  trigger_source: 'planner',
  priority: 0,
  max_iterations: 10,
  timeout_seconds: 600,
};

const buildTask = (overrides: Partial<BackgroundTaskDTO> = {}): BackgroundTaskDTO => ({
  task_id: overrides.task_id ?? 't1',
  status: overrides.status ?? 'running',
  attempt_index: overrides.attempt_index ?? 0,
  spec: overrides.spec ?? DEFAULT_SPEC,
  orchestration_id: overrides.orchestration_id ?? null,
  user_task_id: overrides.user_task_id ?? null,
  summary: overrides.summary ?? null,
  result_payload: overrides.result_payload ?? {},
  error: overrides.error ?? null,
  cancel_reason: overrides.cancel_reason ?? null,
  created_at: overrides.created_at ?? 1,
  started_at: overrides.started_at ?? null,
  finished_at: overrides.finished_at ?? null,
  updated_at: overrides.updated_at ?? 1,
});

describe('useBackgroundTaskStore', () => {
  beforeEach(() => {
    useBackgroundTaskStore.getState().reset();
  });

  it('hydrates tasks and computes active count from the payload', () => {
    const running = buildTask({ task_id: 'a', status: 'running' });
    const done = buildTask({ task_id: 'b', status: 'succeeded' });

    useBackgroundTaskStore.getState().hydrate([running, done], 1);

    const state = useBackgroundTaskStore.getState();
    expect(state.activeCount).toBe(1);
    expect(state.orderedIds).toEqual(['a', 'b']);
    expect(selectOrderedBackgroundTasks(state).map((t) => t.task_id)).toEqual(['a', 'b']);
  });

  it('upserts a new task to the front and recomputes active count', () => {
    const existing = buildTask({ task_id: 'a', status: 'running' });
    useBackgroundTaskStore.getState().hydrate([existing], 1);

    const incoming = buildTask({ task_id: 'b', status: 'pending' });
    useBackgroundTaskStore.getState().upsert(incoming);

    const state = useBackgroundTaskStore.getState();
    expect(state.orderedIds).toEqual(['b', 'a']);
    expect(state.activeCount).toBe(2);
  });

  it('decrements active count when an existing task moves to a terminal status', () => {
    const running = buildTask({ task_id: 'a', status: 'running' });
    useBackgroundTaskStore.getState().hydrate([running], 1);

    useBackgroundTaskStore.getState().upsert({ ...running, status: 'succeeded' });

    expect(useBackgroundTaskStore.getState().activeCount).toBe(0);
  });

  it('remove drops the task from the cache and updates active count', () => {
    const running = buildTask({ task_id: 'a', status: 'running' });
    useBackgroundTaskStore.getState().hydrate([running], 1);

    useBackgroundTaskStore.getState().remove('a');

    const state = useBackgroundTaskStore.getState();
    expect(state.orderedIds).toEqual([]);
    expect(state.tasksById).toEqual({});
    expect(state.activeCount).toBe(0);
  });
});
