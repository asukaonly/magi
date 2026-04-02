import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineClusterBlock } from '@/api/modules/timeline';

interface DayClusterLaneProps {
  clusters: TimelineClusterBlock[];
  onOpenContext: (anchorId: string) => void;
}

const formatDuration = (seconds: number): string => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

const formatTimeRange = (start: number, end: number): string => {
  const fmt = (ts: number) =>
    new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }).format(
      new Date(ts * 1000),
    );
  return `${fmt(start)}–${fmt(end)}`;
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

export const DayClusterLane: React.FC<DayClusterLaneProps> = ({ clusters, onOpenContext }) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-1">
      {clusters.map((cluster) => (
        <article
          key={cluster.block_id}
          role="button"
          tabIndex={0}
          className="group flex cursor-pointer gap-4 rounded-lg px-3 py-3 transition-colors hover:bg-muted/40"
          onClick={() => onOpenContext(cluster.block_id)}
          onKeyDown={(e) => { if (e.key === 'Enter') onOpenContext(cluster.block_id); }}
        >
          {/* Left: time + mode indicator */}
          <div className="flex w-20 shrink-0 flex-col items-end pt-0.5">
            <span className="text-xs tabular-nums text-muted-foreground">
              {formatTimeRange(cluster.time_start, cluster.time_end)}
            </span>
            <span className="mt-1 text-[11px] tabular-nums text-muted-foreground/60">
              {formatDuration(cluster.duration_seconds)}
            </span>
          </div>

          {/* Mode colour bar */}
          <div className="flex w-1 shrink-0 flex-col items-center pt-1">
            <div
              className="h-full w-1 rounded-full"
              style={{ backgroundColor: modeColor(cluster.dominant_mode), opacity: 0.6 }}
            />
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-baseline gap-2">
              <h3 className="truncate text-sm font-medium text-foreground">{cluster.label}</h3>
              <span className="shrink-0 text-xs text-muted-foreground/60">
                {cluster.event_count} {t('timeline.cluster.events')}
              </span>
            </div>

            {cluster.summary && (
              <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
                {cluster.summary}
              </p>
            )}

            <div className="flex flex-wrap gap-1.5">
              {cluster.source_types.map((src) => (
                <span
                  key={src}
                  className="rounded-md bg-secondary/60 px-1.5 py-0.5 text-[11px] text-secondary-foreground"
                >
                  {t(`timeline.sources.${src}`, src)}
                </span>
              ))}
              {cluster.keywords.slice(0, 4).map((kw) => (
                <span key={kw} className="text-[11px] text-muted-foreground/70">
                  #{kw}
                </span>
              ))}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
};

export default DayClusterLane;
