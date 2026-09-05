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

export const getSourcePluginId = (schedule: ScheduleDTO): string => (
  getScheduleStringValue(schedule, 'plugin_id') || schedule.target_key.split(':')[0] || schedule.target_key
);
