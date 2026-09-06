import { describe, expect, it } from 'vitest';
import { scheduleCategory } from '@/pages/tasks-pages/utils/scheduleCategory';

describe('scheduleCategory', () => {
  it('maps user_agent_task to user', () => {
    expect(scheduleCategory('user_agent_task')).toBe('user');
  });
  it('maps source_sync to source', () => {
    expect(scheduleCategory('source_sync')).toBe('source');
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
