export type ScheduleCategory = 'user' | 'source' | 'memory' | 'timeline' | 'other';

export const SCHEDULE_CATEGORIES: ReadonlyArray<ScheduleCategory> = [
  'user',
  'source',
  'memory',
  'timeline',
] as const;

export function scheduleCategory(targetType: string): ScheduleCategory {
  if (targetType === 'user_agent_task') return 'user';
  if (targetType === 'source_sync') return 'source';
  if (targetType.startsWith('memory_')) return 'memory';
  if (targetType.startsWith('timeline_')) return 'timeline';
  return 'other';
}
