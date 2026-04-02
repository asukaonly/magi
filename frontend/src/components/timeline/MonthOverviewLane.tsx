import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineClusterBlock, TimelineReflectionWindow, TimelineStateBand } from '@/api/modules/timeline';

interface MonthOverviewLaneProps {
  reflections: TimelineReflectionWindow[];
  stateBands: TimelineStateBand[];
  clusters: TimelineClusterBlock[];
}

/** Aggregate clusters into a { mode → totalSeconds } distribution map. */
const buildModeDistribution = (clusters: TimelineClusterBlock[]) => {
  const map = new Map<string, number>();
  for (const c of clusters) {
    const mode = c.dominant_mode || 'other';
    map.set(mode, (map.get(mode) || 0) + c.duration_seconds);
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([mode, seconds]) => ({ mode, seconds }));
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
}) => {
  const { t } = useTranslation('app');
  const distribution = buildModeDistribution(clusters);
  const totalSeconds = distribution.reduce((s, d) => s + d.seconds, 0);

  return (
    <div className="space-y-6">
      {/* ── Activity distribution bar ─────────────────────── */}
      {distribution.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('timeline.activity.distribution')}
          </h3>
          {/* Stacked bar */}
          <div className="flex h-2.5 overflow-hidden rounded-sm">
            {distribution.map(({ mode, seconds }) => (
              <div
                key={mode}
                className="transition-all duration-500 first:rounded-l-sm last:rounded-r-sm"
                style={{
                  width: `${(seconds / totalSeconds) * 100}%`,
                  backgroundColor: modeColor(mode),
                  opacity: 0.75,
                }}
                title={`${t(`timeline.sources.${mode}`, mode)} · ${formatDuration(seconds)}`}
              />
            ))}
          </div>
          {/* Legend */}
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {distribution.map(({ mode, seconds }) => (
              <div key={mode} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span
                  className="inline-block h-2 w-2 rounded-[2px]"
                  style={{ backgroundColor: modeColor(mode) }}
                />
                <span>{t(`timeline.sources.${mode}`, mode)}</span>
                <span className="tabular-nums text-muted-foreground/60">{formatDuration(seconds)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Reflection cards ──────────────────────────────── */}
      {reflections.map((reflection) => (
        <article
          key={reflection.reflection_id}
          className="border-l-2 border-primary/30 pl-5"
        >
          <h2 className="text-base font-semibold text-foreground">{reflection.title}</h2>
          <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted-foreground">
            {reflection.summary}
          </p>

          {reflection.key_topics.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {reflection.key_topics.map((topic) => (
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
            <div className="mt-3 rounded-md bg-muted/50 px-3 py-2.5 text-sm">
              <span className="text-xs font-medium text-muted-foreground">
                {t('timeline.reflection.patternSignal')}
              </span>
              <div className="mt-1 text-foreground/80">
                {formatPatternValue(reflection.change_and_pattern)}
              </div>
            </div>
          )}
        </article>
      ))}
    </div>
  );
};

export default MonthOverviewLane;
