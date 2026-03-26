import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineViewportResponse } from '@/api/modules/timeline';
import DayClusterLane from '@/components/timeline/DayClusterLane';
import HourDetailLane from '@/components/timeline/HourDetailLane';
import MonthOverviewLane from '@/components/timeline/MonthOverviewLane';
import StateBandOverlay from '@/components/timeline/StateBandOverlay';

interface TimelineViewportProps {
  scale: 'month' | 'week' | 'day' | 'hour';
  viewport: TimelineViewportResponse;
  onOpenContext: (anchorId: string) => void;
}

export const TimelineViewport: React.FC<TimelineViewportProps> = ({ scale, viewport, onOpenContext }) => {
  const { t } = useTranslation('app');

  return (
    <>
      <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
        <span>{viewport.summary.event_count} {t('timeline.summary.totalEvents')}</span>
        <span>{viewport.summary.cluster_count} {t('timeline.summary.clusterCount')}</span>
      </div>

      <StateBandOverlay bands={viewport.state_bands} markers={viewport.state_markers} scale={scale} />

      {scale === 'month' ? <MonthOverviewLane reflections={viewport.reflections} stateBands={viewport.state_bands} /> : null}
      {(scale === 'week' || scale === 'day') ? <DayClusterLane clusters={viewport.clusters} onOpenContext={onOpenContext} /> : null}
      {scale === 'hour' ? <HourDetailLane rawEvents={viewport.raw_events} /> : null}
    </>
  );
};

export default TimelineViewport;
