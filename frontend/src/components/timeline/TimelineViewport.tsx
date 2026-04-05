import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineClusterBlock, TimelineViewportResponse } from '@/api/modules/timeline';
import DayClusterLane from '@/components/timeline/DayClusterLane';
import DigestCards from '@/components/timeline/DigestCards';
import HighlightCards from '@/components/timeline/HighlightCards';
import HourDetailLane from '@/components/timeline/HourDetailLane';
import MonthOverviewLane from '@/components/timeline/MonthOverviewLane';
import StateBandOverlay from '@/components/timeline/StateBandOverlay';

interface TimelineViewportProps {
  scale: 'month' | 'week' | 'day' | 'hour';
  viewport: TimelineViewportResponse;
  onOpenContext: (anchorId: string) => void;
}

/** Pick "highlight" clusters: high event_count or notable keywords. */
const extractHighlights = (clusters: TimelineClusterBlock[], limit = 3): TimelineClusterBlock[] =>
  [...clusters]
    .sort((a, b) => b.event_count - a.event_count)
    .slice(0, limit);

export const TimelineViewport: React.FC<TimelineViewportProps> = ({ scale, viewport, onOpenContext }) => {
  const { t } = useTranslation('app');

  const highlights = useMemo(
    () => (scale === 'month' || scale === 'week') ? extractHighlights(viewport.clusters) : [],
    [scale, viewport.clusters],
  );

  return (
    <div className="space-y-6">
      {/* Summary counts */}
      <div className="flex gap-4 text-xs text-muted-foreground">
        <span>
          <span className="font-medium tabular-nums text-foreground">{viewport.summary.event_count}</span>{' '}
          {t('timeline.summary.totalEvents')}
        </span>
        <span>
          <span className="font-medium tabular-nums text-foreground">{viewport.summary.cluster_count}</span>{' '}
          {t('timeline.summary.clusterCount')}
        </span>
      </div>

      {/* State bands */}
      <StateBandOverlay bands={viewport.state_bands} markers={viewport.state_markers} scale={scale} />

      {/* Digest (month/week/day) */}
      {(scale === 'month' || scale === 'week' || scale === 'day') && (
        <DigestCards category={scale} />
      )}

      {/* Highlights (month/week) */}
      {highlights.length > 0 && (
        <HighlightCards highlights={highlights} onOpenContext={onOpenContext} />
      )}

      {/* Scale-specific lanes */}
      {scale === 'month' && (
        <MonthOverviewLane
          reflections={viewport.reflections}
          stateBands={viewport.state_bands}
          clusters={viewport.clusters}
        />
      )}
      {(scale === 'week' || scale === 'day') && (
        <DayClusterLane clusters={viewport.clusters} onOpenContext={onOpenContext} />
      )}
      {scale === 'hour' && <HourDetailLane rawEvents={viewport.raw_events} />}
    </div>
  );
};

export default TimelineViewport;
