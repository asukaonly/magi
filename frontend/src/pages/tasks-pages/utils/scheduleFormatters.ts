import type { ScheduleDTO } from '@/api';

export const formatUnixSeconds = (
  ts: number | null | undefined,
  locale?: string,
): string => {
  if (!ts || !Number.isFinite(ts)) return '—';
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(ts * 1000));
};

export const formatScheduleTableTime = (
  ts: number | null | undefined,
  locale?: string,
  todayLabel?: string,
): string => {
  if (!ts || !Number.isFinite(ts)) return '—';
  const date = new Date(ts * 1000);
  const now = new Date();
  const time = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
  const isToday = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  if (isToday && todayLabel) {
    return `${todayLabel} ${time}`;
  }
  const day = new Intl.DateTimeFormat(locale, {
    month: '2-digit',
    day: '2-digit',
  }).format(date);
  return `${day} ${time}`;
};

/**
 * Type-compatible subset of i18next's `t` function. Accepting it as an
 * optional argument lets us localize duration units without importing
 * react-i18next here (this module is pure / framework-free).
 */
export type DurationTFunction = (
  key: string,
  opts?: { defaultValue?: string; [param: string]: unknown },
) => string;

/**
 * Adaptive duration formatter.
 *
 * Picks the most useful unit by magnitude:
 *   - null / NaN / negative → "—"
 *   - <  1 ms               → "<1 ms"
 *   - <  1000 ms            → "{n} ms"
 *   - <  60 s               → "{n} s"   (1 decimal under 10 s)
 *   - <  60 m               → "{m}m {s}s"
 *   - ≥ 1 h                 → "{h}h {m}m"
 *
 * Pass a `t` from useTranslation to localize the units; otherwise English
 * abbreviations are used.
 */
export const formatDuration = (
  durationMs: number | null | undefined,
  t?: DurationTFunction,
): string => {
  if (durationMs == null || !Number.isFinite(durationMs)) return '—';
  if (durationMs < 0) return '—';
  if (durationMs < 1) {
    return t
      ? t('tasks.scheduled.duration.subMs', { defaultValue: '<1 ms' })
      : '<1 ms';
  }
  if (durationMs < 1000) {
    const n = Math.round(durationMs);
    return t
      ? t('tasks.scheduled.duration.ms', { defaultValue: '{{n}} ms', n })
      : `${n} ms`;
  }
  if (durationMs < 60_000) {
    const secs = durationMs / 1000;
    const n = secs < 10 ? secs.toFixed(1) : String(Math.round(secs));
    return t
      ? t('tasks.scheduled.duration.sec', { defaultValue: '{{n}} s', n })
      : `${n} s`;
  }
  if (durationMs < 3_600_000) {
    const totalSecs = Math.round(durationMs / 1000);
    const m = Math.floor(totalSecs / 60);
    const s = totalSecs % 60;
    return t
      ? t('tasks.scheduled.duration.minSec', { defaultValue: '{{m}}m {{s}}s', m, s })
      : `${m}m ${s}s`;
  }
  const totalMins = Math.round(durationMs / 60_000);
  const h = Math.floor(totalMins / 60);
  const m = totalMins % 60;
  return t
    ? t('tasks.scheduled.duration.hourMin', { defaultValue: '{{h}}h {{m}}m', h, m })
    : `${h}h ${m}m`;
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
