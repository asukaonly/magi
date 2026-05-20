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
