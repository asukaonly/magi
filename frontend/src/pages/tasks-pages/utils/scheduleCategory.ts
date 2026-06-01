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
