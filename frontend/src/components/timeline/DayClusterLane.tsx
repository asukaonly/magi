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
        <article key={cluster.block_id} className="rounded-2xl border border-border/60 bg-card/70 p-5">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{cluster.dominant_mode}</span>
                <span className="text-xs text-muted-foreground">{formatDuration(cluster.duration_seconds)}</span>
              </div>
              <h2 className="text-lg font-semibold text-foreground">{cluster.label}</h2>
              <p className="text-sm leading-6 text-muted-foreground">{cluster.summary}</p>
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
