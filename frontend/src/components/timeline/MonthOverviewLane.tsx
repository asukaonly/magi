import React from 'react';
import { useTranslation } from 'react-i18next';

import type {
  TimelineClusterBlock,
  TimelineReflectionWindow,
  TimelineSourceMixItem,
  TimelineStateBand,
} from '@/api/modules/timeline';

interface MonthOverviewLaneProps {
  reflections: TimelineReflectionWindow[];
  stateBands: TimelineStateBand[];
  clusters: TimelineClusterBlock[];
  sourceMix?: TimelineSourceMixItem[];
}

const buildModeDistribution = (clusters: TimelineClusterBlock[], sourceMix?: TimelineSourceMixItem[]) => {
  if (sourceMix?.length) {
    return sourceMix
      .map((item) => ({
        mode: item.source_type,
        seconds: Math.max(0, item.duration_seconds || 0),
        count: Math.max(0, item.event_count || 0),
      }))
      .sort((a, b) => b.count - a.count || b.seconds - a.seconds || a.mode.localeCompare(b.mode));
  }

  const map = new Map<string, { seconds: number; count: number }>();
  for (const c of clusters) {
    const mode = c.dominant_mode || 'other';
    const current = map.get(mode) || { seconds: 0, count: 0 };
    map.set(mode, {
      seconds: current.seconds + Math.max(0, c.duration_seconds || 0),
      count: current.count + Math.max(1, c.event_count || 1),
    });
  }
  return [...map.entries()]
    .sort((a, b) => b[1].seconds - a[1].seconds || b[1].count - a[1].count)
    .map(([mode, value]) => ({ mode, ...value }));
};

const MODE_COLORS: Record<string, string> = {
  chrome_history: 'hsl(210 55% 58%)',
  chat: 'hsl(280 45% 58%)',
  git_activity: 'hsl(150 45% 45%)',
  terminal_history: 'hsl(35 60% 50%)',
  screen_time: 'hsl(340 50% 55%)',
  calendar: 'hsl(190 50% 48%)',
  photo_library: 'hsl(25 65% 55%)',
  netease_music: 'hsl(0 60% 58%)',
  manual_journal: 'hsl(45 55% 50%)',
};

const modeColor = (mode: string): string =>
  MODE_COLORS[mode] || `hsl(${(mode.charCodeAt(0) * 37) % 360} 35% 55%)`;

const formatDuration = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
};

const titleCase = (value: string): string =>
  value
    .replace(/[_-]+/g, ' ')
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

const isInternalReflectionTitle = (title: string): boolean => {
  const normalized = title.trim().toLowerCase();
  return normalized.endsWith('reflection') && (normalized.includes('_') || normalized.includes('shift'));
};

const cleanReflectionTitle = (reflection: TimelineReflectionWindow, fallback: string): string => {
  if (reflection.title && !isInternalReflectionTitle(reflection.title)) {
    return reflection.title;
  }
  const topicTitle = reflection.key_topics.slice(0, 2).map(titleCase).join(' / ');
  return topicTitle || fallback;
};

const formatPatternValue = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.filter(Boolean).join('; ');
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`)
      .join(' · ');
  }
  return String(value ?? '');
};

export const MonthOverviewLane: React.FC<MonthOverviewLaneProps> = ({
  reflections,
  stateBands: _stateBands,
  clusters,
  sourceMix,
}) => {
  const { t } = useTranslation('app');
  const distribution = buildModeDistribution(clusters, sourceMix);
  const totalSeconds = distribution.reduce((s, d) => s + d.seconds, 0);
  const totalCount = distribution.reduce((s, d) => s + d.count, 0);
  const reflectionCards = reflections
    .filter((reflection, index, all) => {
      const key = `${reflection.title}|${reflection.summary}`;
      return all.findIndex((item) => `${item.title}|${item.summary}` === key) === index;
    })
    .slice(0, 6);

  return (
    <div className="space-y-6">
      {distribution.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('timeline.activity.distribution')}
          </h3>
          <div className="flex h-2.5 overflow-hidden rounded-sm">
            {distribution.map(({ mode, seconds, count }) => (
              <div
                key={mode}
                className="transition-all duration-500 first:rounded-l-sm last:rounded-r-sm"
                style={{
                  width: `${((totalSeconds > 0 ? seconds : count) / (totalSeconds > 0 ? totalSeconds : totalCount)) * 100}%`,
                  backgroundColor: modeColor(mode),
                  opacity: 0.75,
                }}
                title={`${t(`timeline.sources.${mode}`, mode)} · ${seconds > 0 ? formatDuration(seconds) : `${count} ${t('timeline.summary.totalEvents')}`}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {distribution.map(({ mode, seconds, count }) => (
              <div key={mode} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className="inline-block h-2 w-2 rounded-[2px]"
                  style={{ backgroundColor: modeColor(mode) }}
                />
                <span>{t(`timeline.sources.${mode}`, mode)}</span>
                <span className="tabular-nums text-muted-foreground/60">
                  {seconds > 0 ? formatDuration(seconds) : `${count} ${t('timeline.summary.totalEvents')}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {reflectionCards.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('timeline.month.themes')}
          </h3>
          <div className="grid gap-3 lg:grid-cols-2">
            {reflectionCards.map((reflection) => (
              <article
                key={reflection.reflection_id}
                className="rounded-lg border border-border/40 bg-card px-4 py-3"
              >
                <h2 className="text-sm font-semibold text-foreground">
                  {cleanReflectionTitle(reflection, t('timeline.reflection.window'))}
                </h2>
                <p className="mt-1.5 line-clamp-3 text-sm leading-relaxed text-muted-foreground">
                  {reflection.summary}
                </p>

                {reflection.key_topics.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {reflection.key_topics.slice(0, 4).map((topic) => (
                      <span
                        key={topic}
                        className="rounded-md bg-secondary px-2 py-0.5 text-xs text-secondary-foreground"
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                )}

                {reflection.change_and_pattern && (
                  <div className="mt-3 border-l-2 border-primary/25 pl-3 text-xs leading-relaxed text-muted-foreground">
                    <span className="font-medium text-foreground/80">
                      {t('timeline.reflection.patternSignal')}
                    </span>{' '}
                    {formatPatternValue(reflection.change_and_pattern)}
                  </div>
                )}
              </article>
            ))}
          </div>
          {reflections.length > reflectionCards.length && (
            <p className="text-xs text-muted-foreground/60">
              {t('timeline.month.moreSignals', { count: reflections.length - reflectionCards.length })}
            </p>
          )}
        </section>
      )}

      {distribution.length === 0 && reflectionCards.length === 0 && (
        <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
          {t('timeline.empty.window')}
        </div>
      )}
    </div>
  );
};

export default MonthOverviewLane;
