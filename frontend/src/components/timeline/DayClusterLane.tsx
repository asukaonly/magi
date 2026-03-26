import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineClusterBlock } from '@/api/modules/timeline';
import { Button } from '@/components/ui/button';

interface DayClusterLaneProps {
  clusters: TimelineClusterBlock[];
  onOpenContext: (anchorId: string) => void;
}

const formatDuration = (durationSeconds: number): string => {
  const hours = Math.floor(durationSeconds / 3600);
  const minutes = Math.floor((durationSeconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
};

export const DayClusterLane: React.FC<DayClusterLaneProps> = ({ clusters, onOpenContext }) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-4">
      {clusters.map((cluster) => (
        <article
          key={cluster.block_id}
          className="overflow-hidden rounded-[28px] border border-border/60 bg-[radial-gradient(circle_at_top_left,rgba(14,116,144,0.12),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(190,24,93,0.1),transparent_36%),linear-gradient(180deg,rgba(255,255,255,0.94),rgba(248,250,252,0.84))] p-5 shadow-[0_18px_60px_-36px_rgba(15,23,42,0.45)] transition-transform duration-200 hover:-translate-y-0.5"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-border/60 bg-white/80 px-2.5 py-1 text-xs font-medium text-foreground">{cluster.dominant_mode}</span>
                <span className="text-xs text-muted-foreground">{formatDuration(cluster.duration_seconds)}</span>
                <span className="rounded-full bg-black/5 px-2.5 py-1 text-xs text-muted-foreground">{cluster.event_count} events</span>
              </div>
              <h2 className="text-xl font-semibold tracking-tight text-foreground">{cluster.label}</h2>
              <p className="text-sm leading-6 text-muted-foreground">{cluster.summary}</p>

              {cluster.state_snapshot ? (
                <div className="grid gap-2 pt-1 sm:grid-cols-3">
                  <div className="rounded-2xl bg-white/70 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Valence</div>
                    <div className="mt-1 text-lg font-semibold text-foreground">{Math.round((cluster.state_snapshot.valence || 0) * 100)}%</div>
                  </div>
                  <div className="rounded-2xl bg-white/70 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Stress</div>
                    <div className="mt-1 text-lg font-semibold text-foreground">{Math.round((cluster.state_snapshot.stress_level || 0) * 100)}%</div>
                  </div>
                  <div className="rounded-2xl bg-white/70 px-3 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Engagement</div>
                    <div className="mt-1 text-lg font-semibold text-foreground">{Math.round((cluster.state_snapshot.engagement || 0) * 100)}%</div>
                  </div>
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2 pt-1">
                {cluster.keywords.map((keyword) => (
                  <span key={keyword} className="rounded-full bg-amber-100/80 px-3 py-1 text-xs font-medium text-amber-950">
                    {keyword}
                  </span>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                {cluster.source_types.map((source) => (
                  <span key={source} className="rounded-full border border-border/60 bg-white/80 px-3 py-1 text-xs text-muted-foreground">
                    {source}
                  </span>
                ))}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              aria-label={`${t('timeline.actions.openContext')}:${cluster.block_id}`}
              onClick={() => onOpenContext(cluster.block_id)}
            >
              {t('timeline.actions.openContext')}
            </Button>
          </div>
        </article>
      ))}
    </div>
  );
};

export default DayClusterLane;
