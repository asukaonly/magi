import React from 'react';
import { useTranslation } from 'react-i18next';

import type { TimelineViewportResponse } from '@/api/modules/timeline';
import type { EpisodeAnnotationPayload } from '@/api/modules/memory';
import DayClusterLane from '@/components/timeline/DayClusterLane';
import HourDetailLane from '@/components/timeline/HourDetailLane';
import MonthOverviewLane from '@/components/timeline/MonthOverviewLane';
import StateBandOverlay from '@/components/timeline/StateBandOverlay';

interface TimelineViewportProps {
  scale: 'month' | 'week' | 'day' | 'hour';
  viewport: TimelineViewportResponse;
  episodeAnnotationPendingId?: string | null;
  onOpenContext: (anchorId: string) => void;
  onAnnotateEpisode?: (episodeId: string, payload: EpisodeAnnotationPayload) => Promise<void> | void;
  onHideEpisode?: (episodeId: string) => Promise<void> | void;
}

const hasViewportContent = (viewport: TimelineViewportResponse): boolean =>
  viewport.summary.event_count > 0
  || viewport.clusters.length > 0
  || viewport.reflections.length > 0
  || viewport.raw_events.length > 0
  || viewport.state_bands.length > 0
  || viewport.state_markers.length > 0;

const EmptyViewport: React.FC = () => {
  const { t } = useTranslation('app');

  return (
    <div className="rounded-lg border border-dashed border-border/60 px-5 py-8 text-sm text-muted-foreground">
      <h2 className="text-base font-medium text-foreground">{t('timeline.feed.emptyTitle')}</h2>
      <p className="mt-2 max-w-2xl leading-relaxed">{t('timeline.feed.emptyBody')}</p>
    </div>
  );
};

export const TimelineViewport: React.FC<TimelineViewportProps> = ({
  scale,
  viewport,
  episodeAnnotationPendingId,
  onOpenContext,
  onAnnotateEpisode,
  onHideEpisode,
}) => {
  const { t } = useTranslation('app');

  if (!hasViewportContent(viewport)) {
    return <EmptyViewport />;
  }

  return (
    <div className="space-y-6">
      <section className="space-y-3 border-b border-border/40 pb-5">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{viewport.overview.title}</span>
            <span>
              <span className="font-medium tabular-nums text-foreground">{viewport.summary.event_count}</span>{' '}
              {t('timeline.summary.totalEvents')}
            </span>
            <span>
              <span className="font-medium tabular-nums text-foreground">{viewport.summary.cluster_count}</span>{' '}
              {t('timeline.summary.clusterCount')}
            </span>
          </div>
          <p className="max-w-4xl text-sm leading-7 text-muted-foreground">
            {viewport.overview.summary}
          </p>
        </div>
        {viewport.overview.key_takeaways.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {viewport.overview.key_takeaways.slice(0, 3).map((takeaway) => (
              <span key={takeaway} className="rounded-md bg-secondary/70 px-2 py-1 text-xs text-secondary-foreground">
                {takeaway}
              </span>
            ))}
          </div>
        )}
      </section>

      <StateBandOverlay bands={viewport.state_bands} stateSummary={viewport.state_summary} scale={scale} />

      {scale === 'month' && (
        <MonthOverviewLane
          sourceMix={viewport.source_mix}
          themeCards={viewport.theme_cards}
          onOpenContext={onOpenContext}
        />
      )}
      {(scale === 'week' || scale === 'day') && (
        <section className="space-y-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t(scale === 'week' ? 'timeline.week.periods' : 'timeline.day.periods')}
          </h3>
          {viewport.clusters.length > 0 ? (
            <DayClusterLane
              scale={scale}
              clusters={viewport.clusters}
              episodeAnnotationPendingId={episodeAnnotationPendingId}
              onOpenContext={onOpenContext}
              onAnnotateEpisode={onAnnotateEpisode}
              onHideEpisode={onHideEpisode}
            />
          ) : (
            <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
              {t('timeline.empty.window')}
            </div>
          )}
        </section>
      )}
      {scale === 'hour' && (
        viewport.raw_events.length > 0 ? (
          <HourDetailLane rawEvents={viewport.raw_events} />
        ) : (
          <div className="rounded-lg border border-dashed border-border/60 px-4 py-6 text-sm text-muted-foreground">
            {t('timeline.empty.window')}
          </div>
        )
      )}
    </div>
  );
};

export default TimelineViewport;
