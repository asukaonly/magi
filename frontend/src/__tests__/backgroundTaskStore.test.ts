import eventExamples from '../../../contracts/api/frontend-events-examples.json';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  selectOrderedBackgroundTasks,
  useBackgroundTaskStore,
} from '@/stores/background-tasks';
import type { BackgroundTaskDTO, BackgroundTaskSpecDTO } from '@/api';
import { applyRealtimeStoreProjection } from '@/realtime/store-projection';

const DEFAULT_SPEC: BackgroundTaskSpecDTO = {
  ...eventExamples.task.spec,
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

const hydrate = (tasks: BackgroundTaskDTO[], activeCount: number) => {
  const state = useBackgroundTaskStore.getState();
  return state.hydrate(tasks, activeCount, state.mutationVersion);
};

describe('useBackgroundTaskStore', () => {
  beforeEach(() => {
    useBackgroundTaskStore.getState().reset();
  });

  it('hydrates tasks and computes active count from the payload', () => {
    const running = buildTask({ task_id: 'a', status: 'running' });
    const done = buildTask({ task_id: 'b', status: 'succeeded' });

    hydrate([running, done], 1);

    const state = useBackgroundTaskStore.getState();
    expect(state.activeCount).toBe(1);
    expect(state.orderedIds).toEqual(['a', 'b']);
    expect(selectOrderedBackgroundTasks(state).map((t) => t.task_id)).toEqual(['a', 'b']);
  });

  it('rejects snapshots started before a live update and ignores older task events', () => {
    const running = buildTask({ task_id: 'a', status: 'running', updated_at: 1 });
    hydrate([running], 1);
    const snapshotVersion = useBackgroundTaskStore.getState().mutationVersion;
    const finished = { ...running, status: 'succeeded' as const, updated_at: 2 };
    useBackgroundTaskStore.getState().upsert(finished);
    expect(useBackgroundTaskStore.getState().hydrate([running], 1, snapshotVersion)).toBe(false);
    expect(useBackgroundTaskStore.getState().upsert(running)).toBe(false);
    expect(useBackgroundTaskStore.getState().tasksById.a).toEqual(finished);
    expect(useBackgroundTaskStore.getState().activeCount).toBe(0);
    hydrate([running], 1);
    expect(useBackgroundTaskStore.getState().tasksById.a).toEqual(finished);
    expect(useBackgroundTaskStore.getState().activeCount).toBe(0);
  });

  it('does not resurrect dismissed tasks from late events or snapshots', () => {
    const task = buildTask({ task_id: 'dismissed', status: 'succeeded' });
    hydrate([task], 0);
    useBackgroundTaskStore.getState().remove(task.task_id);
    expect(useBackgroundTaskStore.getState().upsert(task)).toBe(false);
    hydrate([task], 0);
    expect(useBackgroundTaskStore.getState().orderedIds).toEqual([]);
    const beforeReset = useBackgroundTaskStore.getState().mutationVersion;
    useBackgroundTaskStore.getState().reset();
    expect(useBackgroundTaskStore.getState().hydrate([task], 0, beforeReset)).toBe(false);
  });

  it('upserts a new task to the front and recomputes active count', () => {
    const existing = buildTask({ task_id: 'a', status: 'running' });
    hydrate([existing], 1);

    const incoming = buildTask({ task_id: 'b', status: 'pending' });
    useBackgroundTaskStore.getState().upsert(incoming);

    const state = useBackgroundTaskStore.getState();
    expect(state.orderedIds).toEqual(['b', 'a']);
    expect(state.activeCount).toBe(2);
  });

  it('decrements active count when an existing task moves to a terminal status', () => {
    const running = buildTask({ task_id: 'a', status: 'running' });
    hydrate([running], 1);

    useBackgroundTaskStore.getState().upsert({ ...running, status: 'succeeded' });

    expect(useBackgroundTaskStore.getState().activeCount).toBe(0);
  });

  it('keeps waiting tasks active until they reach a terminal state', () => {
    const running = buildTask();
    hydrate([running], 1);
    useBackgroundTaskStore.getState().upsert({ ...running, status: 'suspended_waiting_user' });
    expect(useBackgroundTaskStore.getState().activeCount).toBe(1);
    useBackgroundTaskStore.getState().upsert({ ...running, status: 'cancelled' });
    expect(useBackgroundTaskStore.getState().activeCount).toBe(0);
  });

  it('remove drops the task from the cache and updates active count', () => {
    const running = buildTask({ task_id: 'a', status: 'running' });
    hydrate([running], 1);

    useBackgroundTaskStore.getState().remove('a');

    const state = useBackgroundTaskStore.getState();
    expect(state.orderedIds).toEqual([]);
    expect(state.tasksById).toEqual({});
    expect(state.activeCount).toBe(0);
  });

  it('blocks retired task events after a full clear but accepts new tasks', () => {
    const oldTask = buildTask({
      task_id: 'old-task',
      created_at: 100,
      updated_at: 100,
    });
    hydrate([oldTask], 1);

    useBackgroundTaskStore.getState().retireForMemoryClear(200);

    expect(applyRealtimeStoreProjection({
      event: 'background_task_state_changed',
      data: {
        ...oldTask,
        status: 'succeeded',
        updated_at: 300,
      },
    })).toBe(false);
    expect(applyRealtimeStoreProjection({
      event: 'background_task_state_changed',
      data: buildTask({
        task_id: 'unknown-old-task',
        created_at: 150,
        updated_at: 300,
      }),
    })).toBe(false);
    expect(applyRealtimeStoreProjection({
      event: 'background_task_state_changed',
      data: buildTask({
        task_id: 'new-task',
        created_at: 201,
        updated_at: 201,
      }),
    })).toBe(true);
    expect(useBackgroundTaskStore.getState().orderedIds).toEqual(['new-task']);
  });

  it('does not resurrect cleared tasks through a later hydration response', () => {
    const oldTask = buildTask({ task_id: 'old-task', created_at: 100 });
    hydrate([oldTask], 1);
    useBackgroundTaskStore.getState().retireForMemoryClear(200);

    hydrate([
      oldTask,
      buildTask({ task_id: 'new-task', created_at: 201, updated_at: 201 }),
    ], 2);

    expect(useBackgroundTaskStore.getState().orderedIds).toEqual(['new-task']);
    expect(useBackgroundTaskStore.getState().activeCount).toBe(1);
  });
});
