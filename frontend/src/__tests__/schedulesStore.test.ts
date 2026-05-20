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

  it('reset clears state', () => {
    useSchedulesStore.getState().hydrate([makeSchedule('a', true)]);
    useSchedulesStore.getState().reset();
    expect(useSchedulesStore.getState().schedules).toEqual([]);
    expect(useSchedulesStore.getState().runningCount).toBe(0);
  });
});
